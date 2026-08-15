#!/usr/bin/env python3
"""run-pipeline.py - run a specify workflow with timestamps and live logs.

specify hides a failing step's stdout/stderr and prints no timestamps. This
wrapper streams specify's own output with an hh:mm:ss prefix, polls the run
state (.specify/workflows/runs/<run_id>/) and prints each step's output as
it finishes, tails the per-role agent logs (<state_dir>/logs/) live, and on
failure prints the resume command.

While specify waits for interactive input on a human gate (its menu window
"┌─ Gate …" is drawn on screen), step results and agent-log lines are
buffered instead of printed, so the window is not flooded; the buffer is
flushed as soon as the engine moves past the gate or the wrapper exits.

On a terminal run the wrapper owns specify's stdin through a pty: specify's
gate step prompts only while its stdin is a TTY, so the slave end is given
to specify (keeping sys.stdin.isatty() True inside it) and terminal input is
forwarded into the master end, so interactive gates keep working while the
wrapper can answer the ADR revise feedback gate itself. When that gate opens
the wrapper creates <state_dir>/tasks/current/feedback.md (never overwriting
an existing file), opens it in the terminal editor ($VISUAL, then $EDITOR,
then nano, then vi), and on editor close answers the gate with `continue` so
the workflow resumes (adr-revise reads feedback.md). If no editor can run
(non-TTY or none found), the file is still created and the gate stays
interactive for manual input. On a non-TTY run no pty is used and specify
keeps the inherited stdin, so gates keep going PAUSED exactly as before.

When the run finishes (success, failure or abort alike) the wrapper prints a
`=== run statistics ===` block: the wall-clock run time and the token/cost
usage of the planner and executor sessions, queried from opencode by session
id. It also plays a single victory.wav signal on gate-open (except the ADR
revise feedback gate), on success and on failure; the sound and the
statistics never change the exit code.

Agent logs are displayed aligned (role labels padded to the longest role
name), agent reasoning longer than 100 chars is truncated for the console
(the full text stays in the .jsonl files), and only lines appended during
the current run are shown (pre-existing log files are baselined at startup).
A step's agent lines print before the step's "--- step X (completed)"
marker.

Usage: run-pipeline.py <workflow-id-or-path> [extra specify args...]
  run-pipeline.py review-pipeline
  run-pipeline.py adr-pipeline -i feature="..."
  run-pipeline.py ~/.config/spec-kit-llm-client/review-pipeline.yml -i branch-diff=true

Environment:
  SKLC_CONFIG          path of the installed config.yml (default: derived
                       from this wrapper's location)
  SKLC_SCRIPTS_DIR     directory of the installed pipeline scripts (set to
                       this wrapper's own directory for the specify child)
  SKLC_ATTACH_FLAG     opencode attach flag passed to run-agent.sh/name-task.sh
                       (set from workflow.use_serve in the installed config)
"""

from __future__ import annotations

import contextlib
import json
import os
import pty
import re
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import termios
import threading
import time
from pathlib import Path

# Step statuses the poller treats as finished. Anything else (running,
# pending, queued, unset) means the step is still in progress and must not be
# reported as a finished event.
TERMINAL_STATUSES = frozenset({"completed", "failed", "skipped"})

# Absolute path of the victory.wav signal: shipped by the installer next to
# this wrapper, so it is resolved from the wrapper's own location at runtime.
SOUND_FILE = Path(__file__).resolve().parent / "victory.wav"

# The installed config.yml: the only runtime source of the workflow settings
# (state_dir, adr_dir, use_serve, human_gates). `__file__` is the wrapper
# FILE (~/.config/opencode/scripts/run-pipeline.py), so ~/.config is three
# `.parent` hops up from it: scripts/ -> opencode/ -> .config/. SKLC_CONFIG
# overrides the location (used by tests).
CONFIG_PATH = Path(
    os.environ.get("SKLC_CONFIG")
    or (Path(__file__).resolve().parent.parent.parent / "spec-kit-llm-client" / "config.yml")
)

# Agent reasoning longer than this is truncated for the console display (the
# full text always stays in the .jsonl files).
MAX_LOG_TEXT_LEN = 100

# Role names are fixed (planner/executor); the longest one sets the label
# width so text after "[role] " starts at the same column.
ROLE_LABEL_WIDTH = 8

# Substring that identifies the ADR revise feedback gate in a step id: the
# plain "adr-feedback-gate", or the loop-iteration form
# "adr-loop:adr-feedback-gate:N". The marker mirrors the step id chosen in
# the installed adr-pipeline.yml: current_step_id from state.json is the
# wrapper's only observation point for "which gate opened", so this is a
# deliberate cross-file coupling — renaming the step silently disables the
# editor path and the gate signals like a normal gate again.
FEEDBACK_GATE_MARKER = "feedback-gate"


def load_config() -> dict:
    """Read the installed config.yml into a dict, or {} on any failure.

    A missing or unreadable file degrades to the documented defaults, so a
    hand-invoked wrapper (or a config deleted after install) still runs.
    """
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import yaml  # installed by the installer (deps.ensure_pyyaml)

        data = yaml.safe_load(text) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def stamp() -> str:
    return time.strftime("%H:%M:%S")


def print_ts(text: str, prefix: str = "") -> None:
    text = text.rstrip()
    if not text:
        return
    for line in text.splitlines():
        print(f"[{stamp()}] {prefix}{line}", flush=True)


def run_id_from_text(text: str) -> str:
    m = re.search(r"Run ID: ([0-9a-f]{8})", text)
    if m:
        return m.group(1)
    try:
        return str(json.loads(text).get("run_id") or "")
    except Exception:
        return ""


# specify-cli v0.16.x draws the human-gate menu with print(): the first line
# of the window starts with these characters (after stripping). This is the
# only observation point for "a gate menu is on screen" — the wrapper's own
# stdout pipe, the same one the menu is drawn into.
GATE_MENU_PREFIX = "┌─ Gate"


def is_gate_menu_opener(line: str) -> bool:
    """True when line is the first line of specify's human-gate menu window.

    Pure string predicate: while such a window is on screen, the wrapper
    buffers its own live output so the menu is not flooded. The menu window
    is drawn only for interactive gates on a TTY; `human_gates: false` and
    non-TTY runs never produce this line, so no suppression happens there.
    """
    return line.strip().startswith(GATE_MENU_PREFIX)


def is_feedback_gate(step_id: str | None) -> bool:
    """True when the step id identifies the ADR revise feedback gate.

    Matches the plain id ("adr-feedback-gate") and the loop-iteration form
    ("adr-loop:adr-feedback-gate:N") by substring. Pure predicate, so the
    gate recognition is unit-testable without a running workflow.
    """
    return bool(step_id) and FEEDBACK_GATE_MARKER in step_id


def truncate(text: str) -> str:
    """Shorten a displayed agent-log text to MAX_LOG_TEXT_LEN chars + "...".

    Agent reasoning events can be very long and flood the console; the full
    text always stays in the .jsonl files — this only shortens the console
    rendering. Pure function.
    """
    if len(text) > MAX_LOG_TEXT_LEN:
        return text[:MAX_LOG_TEXT_LEN] + "..."
    return text


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

    def poll(self, data: dict | None = None) -> list[tuple[str, dict]]:
        """Return (step_id, result) pairs for steps finished since the last poll.

        state.json is read only if the caller has not already read it: the
        monitor reads it once per tick for current_step_id (the gate check)
        and passes the same data in.
        """
        if data is None:
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

    Only meaningful content is shown: `text` parts with a non-empty payload
    (the agents' actual work progression). Marker events (`step-start`,
    `step-finish`) and `text` parts with an empty payload carry no
    information and are dropped entirely — what stays visible from the logs
    is the agents' progression, while failures are reported by the failed
    step's own result and the final status block. Pure function: no file
    state, so the rendering rules are unit-testable without touching the
    log files.
    """
    line = line.strip()
    if not line:
        return role, ""
    try:
        event = json.loads(line)
    except Exception:
        return role, truncate(line)
    part = event.get("part") or {}
    if part.get("type") == "text" and part.get("text"):
        # text parts: print the payload (truncated for the console; the
        # .jsonl file keeps the full text).
        return role, truncate(part["text"])
    return role, ""


class AgentLogTailer:
    """Tails the per-role agent logs (<state_dir>/logs/*.jsonl).

    Construction (which happens before the workflow process starts) takes a
    baseline snapshot of the current sizes of every existing *.jsonl file:
    those files were written by previous runs (the logs dir is never
    cleaned), so each starts at its baseline offset and only lines appended
    during the current run are printed. Files created after the baseline
    start at offset 0.
    """

    def __init__(self, logs_dir: Path) -> None:
        self._logs_dir = logs_dir
        self._log_pos: dict[Path, int] = {}
        if logs_dir.is_dir():
            for path in sorted(logs_dir.glob("*.jsonl")):
                with contextlib.suppress(OSError):
                    self._log_pos[path] = path.stat().st_size

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


def role_label(role: str) -> str:
    """Render the role inside brackets, left-aligned to the longest role
    name: "[planner ]" / "[executor]". Text after the label therefore starts
    at the same column for every role. Pure function.
    """
    return f"[{role.ljust(ROLE_LABEL_WIDTH)}]"


def print_log_event(role: str, text: str) -> None:
    print_ts(text, role_label(role) + " ")


class GateState:
    """Shared, thread-safe marker of an open human-gate menu, owning the
    gate lifecycle.

    The main thread (which reads specify's stdout) calls open(state) when it
    sees the first line of a gate menu window, capturing the gate's step id
    synchronously from the state it reads at that moment; update() advances
    the lifecycle from each later state.json read — closing the gate
    (returning True) once the engine moves past the gate step. The monitor
    thread closes the gate explicitly when the wrapper is stopping (an
    aborted/rejected run may leave current_step_id on the gate forever).
    The lock keeps the flag and the id consistent across the two threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open = False
        self._gate_step_id: str | None = None

    def open(self, state: dict | None) -> None:
        """Mark a gate menu as open, capturing the gate's step id.

        The main thread passes the state.json read made the moment the menu
        opener line arrived: the menu is drawn only while the gate step is
        executing (its current_step_id was saved before input()), so the id
        read here is the gate's own. Capturing it now instead of on a later
        monitor tick removes the window in which a fast answer could make
        the first tick record the next step's id and leave the gate open
        through that whole step. An unreadable state (None) leaves the id
        for update() to capture on the first readable tick.
        """
        with self._lock:
            self._open = True
            self._gate_step_id = (state or {}).get("current_step_id") or None

    def close(self) -> None:
        """Force the gate closed (e.g. the wrapper is stopping)."""
        with self._lock:
            self._open = False
            self._gate_step_id = None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def update(self, state: dict | None) -> bool:
        """Advance the lifecycle from one state.json read.

        While the menu is open: when the captured id is missing (the open
        moment read failed), record current_step_id on the first readable
        tick; when the id differs from the captured one (the user answered
        and the engine moved on), close the gate and return True — the
        caller then flushes whatever output was buffered while the menu was
        open. A failed read (None) only skips the tick: it says nothing
        about the gate, and closing on it would print straight over the
        still-open menu — only a readable state with an empty or different
        current_step_id may close the gate. "Pure" refers to I/O and output
        only: update() never emits output and never touches anything but the
        gate's own state (under its lock) — the "never emits output" clause
        is the contract the caller relies on, since it decides the flush.
        Loop iterations carry distinct suffixed ids (adr-loop:adr-gate:1,
        :2, …), so each re-drawn menu is tracked anew.
        """
        with self._lock:
            if not self._open:
                return False
            if state is None:
                # Transient read failure: skip the tick, keep the gate open.
                return False
            current = state.get("current_step_id") or ""
            if not self._gate_step_id:
                if current:
                    self._gate_step_id = current
                return False
            if current != self._gate_step_id:
                # Inlined instead of close(): the lock is not reentrant.
                self._open = False
                self._gate_step_id = None
                return True
            return False


class LiveMonitor:
    """Coordinates step-result polling and agent-log tailing while specify runs.

    While a human-gate menu is on screen (GateState raised by the stdout
    reader), finished steps and agent-log lines are buffered instead of
    printed; the buffer is flushed when the engine moves past the gate or
    when the wrapper stops.
    """

    def __init__(
        self,
        state_dir: Path,
        prior_runs: set[str],
        logs_dir: Path | None = None,
    ) -> None:
        self.run_id: str = ""
        self._poller = StepResultPoller(state_dir, self.run_id)
        if logs_dir is None:
            logs_dir = Path.cwd() / ".workflow" / "logs"
        self._tailer = AgentLogTailer(logs_dir)
        self._stop = threading.Event()
        self._state_dir = state_dir
        self._prior_runs = prior_runs
        self.gate = GateState()
        self._buffered_steps: list[tuple[str, dict]] = []
        self._buffered_logs: list[tuple[str, str]] = []

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

    def _read_state(self) -> dict | None:
        """Read the current run's state.json, or None when unavailable."""
        try:
            return json.loads(
                (
                    self._state_dir
                    / "workflows"
                    / "runs"
                    / self.run_id
                    / "state.json"
                ).read_text(encoding="utf-8")
            )
        except Exception:
            return None

    def discover_and_read_state(self) -> dict | None:
        """Read the current run's state.json, discovering the run id first.

        Used by main() for the synchronous gate-id capture at the moment a
        menu opener line arrives; the monitor's own poll may not have
        discovered the run id yet. Runs on the calling (main) thread, with
        no lock — that is deliberate: both this method and the monitor's
        poll write the same deterministic value (the single new run
        directory), and attribute assignment is atomic under the GIL, so a
        torn state cannot be observed.
        """
        run_id = self.run_id or self._discover_run_id()
        if not run_id:
            return None
        self.run_id = run_id
        self._poller.run_id = run_id
        return self._read_state()

    def _emit_step(self, step_id: str, result: dict) -> None:
        if self.gate.is_open:
            self._buffered_steps.append((step_id, result))
        else:
            print_step_result(step_id, result)

    def _emit_log(self, role: str, text: str) -> None:
        if self.gate.is_open:
            self._buffered_logs.append((role, text))
        else:
            print_log_event(role, text)

    def _flush_buffer(self) -> None:
        """Print the events that were buffered while the gate menu was open.

        Logs are flushed before the step markers so the "agent lines precede
        the step's completion marker" invariant holds for buffered output
        too; this runs right before live printing resumes, so nothing is
        lost.
        """
        for role, text in self._buffered_logs:
            print_log_event(role, text)
        self._buffered_logs.clear()
        for step_id, result in self._buffered_steps:
            print_step_result(step_id, result)
        self._buffered_steps.clear()

    def _poll_once(self, run_id: str | None = None) -> None:
        if run_id is None:
            run_id = self._discover_run_id()
        state: dict | None = None
        if run_id:
            self.run_id = run_id
            self._poller.run_id = run_id
            # state.json is read once per tick: the gate check needs
            # current_step_id, the poller reuses the same data.
            state = self._read_state()
            if self.gate.update(state):
                # The engine moved past the gate: flush what was buffered
                # while the menu was open, then resume live emission.
                self._flush_buffer()
        # Agent logs are drained BEFORE the step results: a step's final
        # agent lines must print before its "--- step X (completed)" marker,
        # not after it. The logs do not depend on the run id, so they are
        # drained on every tick regardless.
        for role, text in self._tailer.tail():
            self._emit_log(role, text)
        if run_id:
            for step_id, result in self._poller.poll(state):
                # One more tailer drain per finished step: lines written
                # after the drain above (e.g. the agent's final reply before
                # the step completed) print before this step's marker.
                for role, text in self._tailer.tail():
                    self._emit_log(role, text)
                self._emit_step(step_id, result)

    def finish(self) -> None:
        """One final poll after specify exits: late step results may still land.

        The tail thread has already stopped by now, so also drain the agent
        logs once here — otherwise lines written between the last 0.5s poll
        tick and process exit (e.g. the agent's final reply before a step
        completes) are never shown and stay only in the .jsonl files.
        """
        self._poll_once()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._poll_once()
                time.sleep(0.5)
        finally:
            # The wrapper is stopping. An aborted/rejected run may leave
            # current_step_id on the gate, so the gate would never close on
            # its own: close it here and flush whatever was buffered while
            # it was open — nothing is lost.
            self.gate.close()
            self._flush_buffer()


def fmt_thousands(n: int | float) -> str:
    """Format a token count with space thousand separators: 321213 -> '321 213'."""
    return f"{int(n):,}".replace(",", " ")


def fmt_duration(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS (e.g. 6301 -> '01:45:01')."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def notify() -> None:
    """Play the single victory.wav signal, for every event.

    Called when a human-gate menu opens (except the ADR revise feedback
    gate, which the wrapper answers itself and never signals), on a
    successful run and on a failed run alike — one sound for all events,
    never different signals. Playback is non-blocking (the player process is
    not waited for) and degrades quietly: no sound file, no system player or
    a non-TTY stdout simply skip the call, so the exit code and the
    wrapper's output are never affected.
    """
    try:
        if not getattr(sys.stdout, "isatty", lambda: False)():
            return
        if not SOUND_FILE.is_file():
            return
        if sys.platform == "darwin":
            player = shutil.which("afplay")
        elif sys.platform.startswith("win"):
            import winsound  # Windows only

            winsound.PlaySound(
                str(SOUND_FILE), winsound.SND_FILENAME | winsound.SND_ASYNC
            )
            return
        else:
            player = shutil.which("paplay") or shutil.which("aplay")
        if not player:
            return
        subprocess.Popen(
            [player, str(SOUND_FILE)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        # Quiet degradation: a sound problem must never fail the run.
        pass


def read_session_ids(state_dir: Path) -> dict[str, str]:
    """Map role -> session id from <state_dir>/sessions-<task-id>.json.

    The task id is taken from the <state_dir>/tasks/current symlink that the
    workflow's generate-task-id step maintains; a missing or broken symlink
    yields no ids. Only roles with a non-empty id are returned.
    """
    try:
        task_id = (state_dir / "tasks" / "current").resolve().name
    except OSError:
        return {}
    if not task_id:
        return {}
    try:
        data = json.loads(
            (state_dir / f"sessions-{task_id}.json").read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        role: data[role]
        for role in ("planner", "executor")
        if isinstance(data.get(role), str) and data[role]
    }


def export_session_info(session_id: str) -> dict | None:
    """Return the `info` dict of `opencode export <sessionID>`, or None.

    opencode prints the session export as JSON on stdout ("Exporting
    session: …" goes to stderr). The output is captured into a temporary
    file instead of a pipe: opencode (<= 1.18.x) can exit before its piped
    stdout is fully flushed once the session is larger than the pipe buffer,
    silently truncating the JSON. With a file the full output is available;
    a truncated run usually fails to parse, so the export is retried once.
    Any remaining failure — opencode missing, a non-zero exit, unparseable
    output — returns None and the caller degrades to zero/dash values
    instead of failing the run.
    """
    for _ in range(2):
        try:
            with tempfile.TemporaryFile(mode="w+b") as out:
                result = subprocess.run(
                    ["opencode", "export", session_id],
                    stdout=out,
                    stderr=subprocess.DEVNULL,
                    timeout=120,
                )
                if result.returncode != 0:
                    return None
                out.seek(0)
                try:
                    info = json.loads(out.read().decode("utf-8"))["info"]
                except Exception:
                    continue  # truncated/invalid export: retry once
                return info if isinstance(info, dict) else None
        except Exception:
            return None
    return None


def collect_usage(state_dir: Path) -> dict[str, int | float]:
    """Aggregate token usage and cost across the planner and executor sessions.

    Sums info.tokens.{input,output,reasoning}, info.tokens.cache.{read,write}
    and info.cost of both roles into one dict; a role with no session id or a
    failed export contributes nothing. No live token accumulator is involved:
    opencode reports the full usage of each saved session itself.
    """
    totals: dict[str, int | float] = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost": 0.0,
    }
    for session_id in read_session_ids(state_dir).values():
        info = export_session_info(session_id)
        if info is None:
            continue
        tokens = info.get("tokens")
        if isinstance(tokens, dict):
            totals["input"] += int(tokens.get("input") or 0)
            totals["output"] += int(tokens.get("output") or 0)
            totals["reasoning"] += int(tokens.get("reasoning") or 0)
            cache = tokens.get("cache")
            if isinstance(cache, dict):
                totals["cache_read"] += int(cache.get("read") or 0)
                totals["cache_write"] += int(cache.get("write") or 0)
        cost = info.get("cost")
        if isinstance(cost, (int, float)):
            totals["cost"] += float(cost)
    return totals


def print_run_statistics(state_dir: Path, elapsed: float) -> None:
    """Print the final `=== run statistics ===` block.

    Printed after the run on every completion path (success, failure, abort).
    Token counts use space thousand separators; wall time is HH:MM:SS.
    Missing session data degrades to zeros — the wrapper never fails here.
    """
    usage = collect_usage(state_dir)
    print()
    print("=== run statistics ===")
    print(f"wall time: {fmt_duration(elapsed)}")
    print(
        "tokens: input {} · output {} · reasoning {}".format(
            fmt_thousands(usage["input"]),
            fmt_thousands(usage["output"]),
            fmt_thousands(usage["reasoning"]),
        )
    )
    print(
        "cache: read {} · write {}".format(
            fmt_thousands(usage["cache_read"]),
            fmt_thousands(usage["cache_write"]),
        )
    )
    print("cost: ${:.2f}".format(usage["cost"]))


def resolve_editor() -> list[str] | None:
    """Resolve the terminal editor for the feedback file.

    Order: $VISUAL, then $EDITOR, then nano, then vi. A $VISUAL/$EDITOR
    value may carry arguments (`code --wait`) and is split like a shell
    command line (a malformed value is skipped with a warning, as in the
    launcher); the first candidate whose binary is found on PATH wins. None
    means no editor is available at all and the feedback gate falls back to
    manual input. Unlike the launcher's `_resolve_editor` (which must always
    open *something*), here a missing binary falls through to the next
    candidate and a fully empty chain is reported as None.
    """
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var)
        if not value:
            continue
        try:
            cmd = shlex.split(value)
        except ValueError as exc:
            print(
                f"warning: {var} is malformed ({exc}); skipping it",
                file=sys.stderr,
            )
            continue
        if cmd and shutil.which(cmd[0]):
            return cmd
    for name in ("nano", "vi"):
        if shutil.which(name):
            return [name]
    return None


def create_feedback_file(path: Path) -> None:
    """Create the empty feedback.md for the revise gate.

    Never overwrites an existing file: the planner may have written one, or
    the user may have started writing during an earlier fallback.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()


def open_feedback_editor(
    feedback_path: Path, pause: threading.Event, master_fd: int
) -> bool:
    """Own the ADR revise feedback gate.

    Pauses stdin forwarding, creates feedback.md (never overwriting), opens
    it in the terminal editor (which inherits the real terminal, not the
    pty, so there is no race with the gate's input()) and, on editor close,
    answers the gate with `continue` so the workflow continues (adr-revise
    reads feedback.md). Returns True when the wrapper answered the gate;
    False on fallback — no TTY or no editor on PATH — where the file is
    still created, forwarding is left running and the gate stays interactive
    for manual input.
    """
    create_feedback_file(feedback_path)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    editor = resolve_editor()
    if editor is None:
        return False
    pause.set()
    try:
        try:
            subprocess.run([*editor, str(feedback_path)], check=False)
        except OSError as exc:
            print(
                f"error: cannot start editor {editor[0]}: {exc}",
                file=sys.stderr,
            )
            return False
        # "continue" is the option declared on the adr-feedback-gate step
        # (options: [continue, abort] in the installed adr-pipeline.yml); the
        # wrapper hardcodes it because it has no parsed handle on the
        # workflow's options, so this string is a cross-file contract, not a
        # free-form answer — a mismatch makes specify reject it and the gate
        # silently degrades to manual input. The answer is written while
        # forwarding is still paused: it is guaranteed to be the first thing
        # the gate's input() reads.
        with contextlib.suppress(OSError):
            os.write(master_fd, b"continue\n")
        return True
    finally:
        pause.clear()


def forward_terminal_input(
    source, master_fd: int, pause: threading.Event, stop: threading.Event
) -> None:
    """Forward terminal input to specify's pty stdin.

    Runs in a background thread while specify runs; the main thread pauses
    it (pause.set()) while the feedback editor is open so the user's
    keystrokes reach only the editor. Exits on terminal EOF or when stop is
    set.
    """
    while not stop.is_set():
        if pause.is_set():
            time.sleep(0.05)
            continue
        try:
            readable, _, _ = select.select([source], [], [], 0.1)
        except (OSError, ValueError):
            return
        if not readable:
            continue
        try:
            line = source.readline()
        except (OSError, ValueError):
            return
        if not line:
            return  # terminal EOF: nothing more to forward
        try:
            os.write(master_fd, line.encode("utf-8"))
        except (OSError, ValueError):
            return


def set_pty_no_echo(fd: int) -> None:
    """Disable ECHO on the pty slave (best effort).

    The user already sees their keystrokes echoed by the real terminal; a
    pty-side ECHO would only accumulate echoed bytes in the master's read
    buffer. termios failure leaves the pty at its defaults.
    """
    try:
        attrs = termios.tcgetattr(fd)
        # tcgetattr returns a 7-element list; index 3 is the local-flags
        # field (lflag), where ECHO/ECHONL live — clearing them there stops
        # the pty from echoing, without touching the other modes.
        attrs[3] &= ~(termios.ECHO | termios.ECHONL)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (OSError, ValueError):
        pass


def build_specify_invocation(
    cfg: dict, source: str, extra: list[str]
) -> tuple[list[str], dict[str, str], str, Path]:
    """Map the installed config + argv to the specify invocation.

    The single place that turns config.yml into the launch of specify;
    returns (specify_cmd, env, state_dir, logs_dir) so main() only
    orchestrates the live run. No run-side I/O happens here:

    - state_dir/adr_dir go to the workflow as -i inputs (its steps reference
      {{ inputs.state_dir }} / {{ inputs.adr_dir }});
    - use_serve becomes the SKLC_ATTACH_FLAG env var for
      run-agent.sh/name-task.sh;
    - human_gates decides whether the ADR gate's verdict input is passed as
      empty (interactive) or left to its "approve" default (auto-approve);
    - run-agent.sh keeps its sessions/logs/pids under the same state dir the
      workflow steps write artifacts to, so it must see SKLC_STATE_DIR.
    """
    workflow = cfg.get("workflow") or {}
    state_dir = workflow.get("state_dir") or ".workflow"
    adr_dir = workflow.get("adr_dir") or "architecture"
    use_serve = bool(workflow.get("use_serve", False))
    human_gates = bool(workflow.get("human_gates", True))
    attach_flag = "--attach http://localhost:4096" if use_serve else ""
    scripts_dir = str(Path(__file__).resolve().parent)
    env = dict(os.environ)
    env["SKLC_SCRIPTS_DIR"] = scripts_dir
    env["SKLC_ATTACH_FLAG"] = attach_flag
    env["SKLC_STATE_DIR"] = state_dir

    specify_cmd = [
        "specify",
        "workflow",
        "run",
        source,
        "-i",
        f"state_dir={state_dir}",
        "-i",
        f"adr_dir={adr_dir}",
    ]
    if human_gates:
        # Interactive gates: an empty adr_verdict falls through to the human
        # prompt. Non-interactive runs omit it, so the declared default
        # "approve" auto-approves the ADR gate (matching human_gates: false).
        specify_cmd += ["-i", "adr_verdict="]
    specify_cmd += extra

    logs_dir = Path.cwd() / state_dir / "logs"
    return specify_cmd, env, state_dir, logs_dir


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    source = argv[0]
    extra = argv[1:]

    # Map the installed config + argv to the specify invocation; main() only
    # orchestrates the live run from the result.
    cfg = load_config()
    specify_cmd, env, state_dir, logs_dir = build_specify_invocation(cfg, source, extra)

    state_root = Path.cwd() / ".specify"
    # Snapshot the existing run directories BEFORE the workflow starts: the
    # run id is only printed by specify after the run finishes, so the
    # monitor recognizes the current run as the run dir that appears now.
    prior_runs = existing_run_ids(state_root)
    monitor = LiveMonitor(state_root, prior_runs, logs_dir)
    # Wall-clock run time is measured directly around the child process; it
    # covers every completion path (success, failure, abort).
    t0 = time.monotonic()

    # The wrapper owns specify's stdin only on a terminal run: a pty keeps
    # sys.stdin.isatty() True inside specify (its gate step goes PAUSED on a
    # non-TTY stdin, see ADR-0002), so interactive gates prompt as before
    # while the wrapper can still inject the feedback-gate answer itself.
    # On a non-TTY run specify keeps the inherited stdin (also non-TTY), so
    # gates go PAUSED and no "┌─ Gate" menu is drawn — exactly the
    # documented non-interactive behavior.
    master_fd: int | None = None
    forward_pause = threading.Event()
    forward_stop = threading.Event()
    if sys.stdin.isatty():
        master_fd, slave_fd = pty.openpty()
        set_pty_no_echo(slave_fd)
        proc = subprocess.Popen(
            specify_cmd,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        os.close(slave_fd)
        forward_thread = threading.Thread(
            target=forward_terminal_input,
            args=(sys.stdin, master_fd, forward_pause, forward_stop),
            daemon=True,
        )
        forward_thread.start()
    else:
        proc = subprocess.Popen(
            specify_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    monitor.start()
    run_id = ""
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            if is_gate_menu_opener(line):
                # A human-gate menu window appeared on screen: pause the
                # monitor's own output (buffered until the gate closes).
                # The gate's step id is captured synchronously from the
                # state read right now — not on a later monitor tick, when
                # a fast answer could already have moved current_step_id.
                # Echo of the menu lines themselves is unchanged below.
                state = monitor.discover_and_read_state()
                monitor.gate.open(state)
                if is_feedback_gate((state or {}).get("current_step_id")):
                    # The ADR revise feedback gate: the wrapper owns the
                    # answer. feedback.md is created (never overwritten) and
                    # opened in the terminal editor; on editor close the
                    # gate is answered with `continue` so the workflow
                    # continues (adr-revise reads feedback.md). If no editor
                    # can run, the gate stays interactive for manual input.
                    # No victory sound is played for this gate in any path.
                    if master_fd is not None:
                        open_feedback_editor(
                            Path.cwd()
                            / state_dir
                            / "tasks"
                            / "current"
                            / "feedback.md",
                            forward_pause,
                            master_fd,
                        )
                else:
                    # The human is needed: play the same signal used for a
                    # finished run (success or failure alike).
                    notify()
            print(f"[{stamp()}] {line}", flush=True)
            if not run_id:
                run_id = run_id_from_text(line)
                if run_id:
                    monitor.run_id = run_id
    finally:
        # Stop stdin forwarding and release the pty before reaping the
        # child: the forward thread would otherwise keep writing into the
        # pty while the wrapper exits.
        forward_stop.set()
        if master_fd is not None:
            forward_thread.join(timeout=1)
            with contextlib.suppress(OSError):
                os.close(master_fd)
        # Reap the child even when the read loop above raised (OSError,
        # KeyboardInterrupt) before reaching proc.wait(): otherwise
        # proc.returncode would be None and the failure message would print
        # "run failed (exit None)". wait() is a no-op when the process
        # already exited.
        proc.wait()
        t1 = time.monotonic()
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
        print(f"[{stamp()}] run failed (exit {rc})")
        if run_id or monitor.run_id:
            print(
                f"[{stamp()}] resume with: specify workflow resume {run_id or monitor.run_id}"
            )
    # The statistics block prints on every completion path and never fails:
    # missing session data or a failed `opencode export` degrade to zeros.
    print_run_statistics(Path.cwd() / state_dir, t1 - t0)
    # One victory.wav signal for every event: gate open, success, failure.
    notify()
    return rc


if __name__ == "__main__":
    sys.exit(main())
