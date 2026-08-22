"""Unit tests for the StepResultPoller class."""

import json
import tempfile
import unittest
from pathlib import Path

from .helpers import load_run_pipeline


class StepResultPollerTest(unittest.TestCase):
    def _run_dir(self, tmp: str, run_id: str = "abc12345") -> Path:
        run_dir = Path(tmp) / "workflows" / "runs" / run_id
        run_dir.mkdir(parents=True)
        return run_dir

    def test_non_terminal_statuses_never_reported(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run_dir(tmp)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "step_results": {
                            "running-step": {"status": "running"},
                            "pending-step": {"status": "pending"},
                            "gate": {"status": "completed", "output": {"stdout": "ok"}},
                        }
                    }
                ),
                encoding="utf-8",
            )
            poller = mod.StepResultPoller(Path(tmp), "abc12345")
            first = poller.poll()
            self.assertEqual([step for step, _ in first], ["gate"])
            self.assertEqual(poller.poll(), [])

    def test_step_completing_later_is_reported_once(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run_dir(tmp)
            state_file = run_dir / "state.json"
            state_file.write_text(
                json.dumps({"step_results": {"write-adr": {"status": "pending"}}}),
                encoding="utf-8",
            )
            poller = mod.StepResultPoller(Path(tmp), "abc12345")
            # pending is not a finished event...
            self.assertEqual(poller.poll(), [])
            # ...but once the step terminates it is reported, exactly once.
            state_file.write_text(
                json.dumps({"step_results": {"write-adr": {"status": "failed"}}}),
                encoding="utf-8",
            )
            events = poller.poll()
            self.assertEqual([step for step, _ in events], ["write-adr"])
            self.assertEqual(poller.poll(), [])
