#!/usr/bin/env python3
"""run-pipeline.py - run a specify workflow with timestamps and live logs.

specify hides a failing step's stdout/stderr and prints no timestamps. This
wrapper streams specify's own output with an hh:mm:ss prefix, polls the run
state (.specify/workflows/runs/<run_id>/) and prints each step's output as
it finishes, tails the per-role agent logs (<state_dir>/logs/) live, and on
failure prints the resume command.

Usage: run-pipeline.py <workflow-id-or-path> [extra specify args...]
  run-pipeline.py review-pipeline
  run-pipeline.py adr-pipeline -i feature="..."
  run-pipeline.py ~/.config/spec-kit-llm-client/review-pipeline.yml -i branch-diff=true
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

# Step statuses the poller treats as finished. Anything else (running,
# pending, queued, unset) means the step is still in progress and must not be
# reported as a finished event.
TERMINAL_STATUSES = frozenset({"completed", "failed", "skipped"})


def stamp() -> str:
    return time.strftime("%H:%M:%S")


def print_ts(text: str, prefix: str = "") -> None:
    text = text.rstrip()
    if not text:
        return
    for line in text.splitlines():
        print("[{}] {}{}".format(stamp(), prefix, line), flush=True)


def run_id_from_text(text: str) -> str:
    m = re.search(r"Run ID: ([0-9a-f]{8})", text)
    if m:
        return m.group(1)
    try:
        return str(json.loads(text).get("run_id") or "")
    except Exception:
        return ""


def existing_run_ids(state_dir: Path) -> set[str]:
    """Names of the run directories already present under state_dir/runs.

    Snapshot these BEFORE the workflow process starts: a run directory that
    appears afterwards belongs to this invocation, and that is the only
    reliable way to recognize it. Guessing by newest mtime is not reliable
    here either — a resumed run keeps its original mtime, and a concurrent
    run could be newer.
    """
    runs_dir = state_dir / "workflows" / "runs"
    try:
        return {p.name for p in runs_dir.iterdir() if p.is_dir()}
    except OSError:
        return set()


class StepResultPoller:
    """Polls state.json for step results that finished since the last poll."""

    def __init__(self, state_dir: Path, run_id: str = "") -> None:
        self.state_dir = state_dir
        self.run_id = run_id
        self._seen_steps: set[str] = set()

    def _run_dir(self) -> Path:
        return self.state_dir / "workflows" / "runs" / self.run_id

    def poll(self) -> list[tuple[str, dict]]:
        """Return (step_id, result) pairs for steps finished since the last poll."""
        try:
            data = json.loads(
                (self._run_dir() / "state.json").read_text(encoding="utf-8")
            )
        except Exception:
            return []
        events: list[tuple[str, dict]] = []
        for step_id, result in data.get("step_results", {}).items():
            if step_id in self._seen_steps or result.get("status") not in TERMINAL_STATUSES:
                continue
            self._seen_steps.add(step_id)
            events.append((step_id, result))
        return events


def render_log_event(role: str, line: str) -> tuple[str, str]:
    """Map one raw log line to the (role, text) pair to display.

    Pure function: no file state, so the rendering rules are unit-testable
    without touching the log files.
    """
    line = line.strip()
    if not line:
        return role, ""
    try:
        event = json.loads(line)
    except Exception:
        return role, line
    part = event.get("part") or {}
    if part.get("type") == "text" and part.get("text"):
        # text parts: print the payload.
        return role, part["text"]
    if part.get("type") in ("text", "step-start", "step-finish"):
        # "text" in this branch means a text part with an EMPTY payload
        # (rare); step markers carry no payload either. All three fall back
        # to the event-level type as a marker line — event.type, not
        # part.type ("message" vs "text", "step-start" vs "step-start").
        return role, "{}".format(event.get("type"))
    return role, ""


class AgentLogTailer:
    """Tails the per-role agent logs (<state_dir>/logs/*.jsonl)."""

    def __init__(self, logs_dir: Path) -> None:
        self._logs_dir = logs_dir
        self._log_pos: dict[Path, int] = {}

    def tail(self) -> list[tuple[str, str]]:
        """Return (role, text) pairs for log lines appended since the last tail.

        Raw file reading (byte offsets) lives in _read_appended(); the
        interpretation of each line into a (role, text) pair is the pure
        render_log_event().
        """
        if not self._logs_dir.is_dir():
            return []
        events: list[tuple[str, str]] = []
        for path in sorted(self._logs_dir.glob("*.jsonl")):
            lines, _ = self._read_appended(path)
            if not lines:
                continue
            role = path.stem.rsplit("-", 1)[-1]
            for line in lines:
                role, text = render_log_event(role, line)
                if text:
                    events.append((role, text))
        return events

    def _read_appended(self, path: Path) -> tuple[list[str], int]:
        """Read the lines appended to path since the last tail.

        Returns (lines, new_offset). Tracks raw byte offsets per log file so
        each line is yielded exactly once even when the file grows between
        polls; the lines are returned uninterpreted. A trailing line without
        a terminating newline (an in-progress write) is NOT consumed — it is
        re-read on the next poll, so a half-written JSON event is never
        rendered as a broken raw line. The recorded offset advances only
        after a successful read, so a transient OSError cannot permanently
        skip a chunk.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return [], self._log_pos.get(path, 0)
        offset = self._log_pos.get(path, 0)
        if size < offset:
            offset = 0
        if size <= offset:
            return [], offset
        try:
            with path.open(encoding="utf-8") as fh:
                fh.seek(offset)
                data = fh.read()
        except OSError:
            # Position unchanged: the same chunk is retried next poll.
            return [], self._log_pos.get(path, 0)
        if not data:
            return [], offset
        last_nl = data.rfind("\n")
        if last_nl == -1:
            # Only an unterminated line: nothing complete to consume.
            return [], offset
        complete = data[: last_nl + 1]
        lines = complete.splitlines()
        # Offsets are BYTE offsets: they come from path.stat().st_size and are
        # fed to fh.seek(). len(complete) counts characters, so re-encode to
        # get the byte length — otherwise multibyte UTF-8 lines (e.g. Russian
        # ADR text in the agent events) make new_offset land mid-character,
        # and the next poll's fh.read() raises UnicodeDecodeError (a
        # ValueError, which the except OSError above does not catch), killing
        # the tailer thread.
        new_offset = offset + len(complete.encode("utf-8"))
        self._log_pos[path] = new_offset
        return lines, new_offset


def print_step_result(step_id: str, result: dict) -> None:
    print_ts("--- step {} ({})".format(step_id, result.get("status")))
    out = result.get("output") or {}
    print_ts(out.get("stdout") or "", "    ")
    stderr = out.get("stderr") or ""
    if stderr:
        print_ts(stderr, "    [err] ")


def print_log_event(role: str, text: str) -> None:
    print_ts(text, "[{}] ".format(role))


class LiveMonitor:
    """Coordinates step-result polling and agent-log tailing while specify runs."""

    def __init__(self, state_dir: Path, prior_runs: set[str]) -> None:
        self.run_id: str = ""
        self._poller = StepResultPoller(state_dir, self.run_id)
        self._tailer = AgentLogTailer(Path.cwd() / '${state_dir}/logs')
        self._stop = threading.Event()
        self._state_dir = state_dir
        self._prior_runs = prior_runs

    def _discover_run_id(self) -> str:
        """Find the run id for the workflow this wrapper started, if unknown.

        `specify workflow run` prints "Run ID: <id>" only AFTER the workflow
        finishes, so during the run the id can only come from the run
        directory that appeared under .specify/workflows/runs/ since the
        wrapper started; without it the step-result poller would poll
        runs/<empty> for the whole run and never print live step output.
        """
        if self.run_id:
            return self.run_id
        for name in sorted(existing_run_ids(self._state_dir) - self._prior_runs):
            return name
        return ""

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self) -> None:
        self._thread.join()

    def _poll_once(self, run_id: str | None = None) -> None:
        if run_id is None:
            run_id = self._discover_run_id()
        if run_id:
            self.run_id = run_id
            self._poller.run_id = run_id
            for step_id, result in self._poller.poll():
                print_step_result(step_id, result)
        # The agent logs are drained on every tick regardless of the run id
        # (they do not depend on it); before the run id is known the tailer
        # still shows live agent output.
        for role, text in self._tailer.tail():
            print_log_event(role, text)

    def finish(self) -> None:
        """One final poll after specify exits: late step results may still land.

        The tail thread has already stopped by now, so also drain the agent
        logs once here — otherwise lines written between the last 0.5s poll
        tick and process exit (e.g. the agent's final reply before a step
        completes) are never shown and stay only in the .jsonl files.
        """
        self._poll_once()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            time.sleep(0.5)


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    source = argv[0]
    extra = argv[1:]

    state_root = Path.cwd() / ".specify"
    # Snapshot the existing run directories BEFORE the workflow starts: the
    # run id is only printed by specify after the run finishes, so the
    # monitor recognizes the current run as the run dir that appears now.
    prior_runs = existing_run_ids(state_root)
    monitor = LiveMonitor(state_root, prior_runs)
    proc = subprocess.Popen(
        ["specify", "workflow", "run", source, *extra],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    monitor.start()
    run_id = ""
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            print("[{}] {}".format(stamp(), line), flush=True)
            if not run_id:
                run_id = run_id_from_text(line)
                if run_id:
                    monitor.run_id = run_id
    finally:
        # Reap the child even when the read loop above raised (OSError,
        # KeyboardInterrupt) before reaching proc.wait(): otherwise
        # proc.returncode would be None and the failure message would print
        # "run failed (exit None)". wait() is a no-op when the process
        # already exited.
        proc.wait()
        # Stop and join the monitor thread first: finish() below would
        # otherwise race _run()'s poll() on the shared _seen_steps state and
        # can duplicate a step's output.
        monitor.stop()
        monitor.join()
        # The stdout "Run ID:" line may never appear (e.g. the workflow
        # failed before the final status block), but the run directory was
        # already discovered; drain late results and logs either way.
        if run_id or monitor.run_id:
            time.sleep(0.2)
            monitor.finish()
    rc = proc.returncode
    if rc is None:
        rc = 1
    if rc != 0:
        print()
        print("[{}] run failed (exit {})".format(stamp(), rc))
        if run_id or monitor.run_id:
            print(
                "[{}] resume with: specify workflow resume {}".format(
                    stamp(), run_id or monitor.run_id
                )
            )
    return rc


if __name__ == "__main__":
    sys.exit(main())
