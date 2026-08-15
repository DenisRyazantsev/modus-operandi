"""StepResultPoller: poll state.json for step results that finished since the last poll."""

from __future__ import annotations

import json
from pathlib import Path

from _run_pipeline_common import TERMINAL_STATUSES


class StepResultPoller:
    """Polls state.json for step results that finished since the last poll."""

    def __init__(self, run_state_dir: Path, run_id: str = "") -> None:
        self.run_state_dir = run_state_dir
        self.run_id = run_id
        self._seen_steps: set[str] = set()

    def _run_dir(self) -> Path:
        return self.run_state_dir / "workflows" / "runs" / self.run_id

    def read_state(self) -> dict | None:
        """Read the current run's state.json, or None when unavailable.

        The raw state.json I/O for the current run: the monitor calls this
        once per tick and hands the same dict to poll() (which only parses
        finished-step events out of it) and to the gate lifecycle (which
        needs current_step_id).
        """
        try:
            return json.loads(
                (self._run_dir() / "state.json").read_text(encoding="utf-8")
            )
        except Exception:
            return None

    def poll(self, data: dict | None = None) -> list[tuple[str, dict]]:
        """Return (step_id, result) pairs for steps finished since the last poll.

        state.json is read only if the caller has not already read it: the
        monitor reads it once per tick for current_step_id (the gate check)
        and passes the same data in.
        """
        if data is None:
            data = self.read_state()
            if data is None:
                return []
        events: list[tuple[str, dict]] = []
        for step_id, result in data.get("step_results", {}).items():
            if step_id in self._seen_steps or result.get("status") not in TERMINAL_STATUSES:
                continue
            self._seen_steps.add(step_id)
            events.append((step_id, result))
        return events
