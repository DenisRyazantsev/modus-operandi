#!/usr/bin/env python3
"""run-pipeline.py - run a specify workflow with timestamps and live logs.

specify hides a failing step's stdout/stderr and prints no timestamps. This
wrapper streams specify's own output with an hh:mm:ss prefix, polls the run
state (.specify/workflows/runs/<run_id>/) and prints each step's output as
it finishes, tails the per-role agent logs (.workflow/logs/) live, and on
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


class LiveMonitor:
    """Polls the run state and tails the agent logs while specify runs."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.run_id: str = ""
        self._seen_steps: set[str] = set()
        self._log_pos: dict[Path, int] = {}
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            if self.run_id:
                self._poll_state()
                self._tail_logs()
            time.sleep(0.5)

    def _run_dir(self) -> Path:
        return self.state_dir / "workflows" / "runs" / self.run_id

    def _poll_state(self) -> None:
        try:
            data = json.loads(
                (self._run_dir() / "state.json").read_text(encoding="utf-8")
            )
        except Exception:
            return
        for step_id, result in data.get("step_results", {}).items():
            if step_id in self._seen_steps or result.get("status") == "running":
                continue
            self._seen_steps.add(step_id)
            print_ts("--- step {} ({})".format(step_id, result.get("status")))
            out = result.get("output") or {}
            print_ts(out.get("stdout") or "", "    ")
            stderr = out.get("stderr") or ""
            if stderr:
                print_ts(stderr, "    [err] ")

    def _tail_logs(self) -> None:
        logs_dir = Path.cwd() / ".workflow" / "logs"
        if not logs_dir.is_dir():
            return
        for path in sorted(logs_dir.glob("*.jsonl")):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            offset = self._log_pos.get(path, 0)
            if size < offset:
                offset = 0
            if size <= offset:
                continue
            self._log_pos[path] = size
            try:
                with path.open(encoding="utf-8") as fh:
                    fh.seek(offset)
                    lines = fh.read().splitlines()
            except OSError:
                continue
            role = path.stem.rsplit("-", 1)[-1]
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    print_ts(line, "[{}] ".format(role))
                    continue
                part = event.get("part") or {}
                if part.get("type") == "text" and part.get("text"):
                    print_ts(part["text"], "[{}] ".format(role))
                elif part.get("type") in ("text", "step-start", "step-finish"):
                    print_ts("{}".format(event.get("type")), "[{}] ".format(role))


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    source = argv[0]
    extra = argv[1:]

    monitor = LiveMonitor(Path.cwd() / ".specify")
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
        proc.wait()
    finally:
        if run_id:
            time.sleep(0.2)
            monitor._poll_state()
        monitor.stop()
    rc = proc.returncode
    if rc != 0:
        print()
        print("[{}] run failed (exit {})".format(stamp(), rc))
        if run_id:
            print("[{}] resume with: specify workflow resume {}".format(stamp(), run_id))
    return rc


if __name__ == "__main__":
    sys.exit(main())
