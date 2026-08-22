"""Unit tests for run-id discovery through the LiveMonitor."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import cwd, stdout

from .helpers import load_run_pipeline


class RunIdDiscoveryTest(unittest.TestCase):
    """The wrapper cannot learn the run id from stdout until the workflow
    finishes ("Run ID:" prints last), so the monitor must discover the run
    directory created since the wrapper started and poll it live."""

    def _state(self, tmp: str) -> Path:
        runs = Path(tmp) / "workflows" / "runs"
        runs.mkdir(parents=True)
        return Path(tmp)

    def test_new_run_dir_is_discovered_and_polled(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp)
            captured = io.StringIO()
            with (
                cwd(tmp),
                stdout(captured),
            ):
                monitor = mod.LiveMonitor(state, mod.existing_run_ids(state))
                run_dir = state / "workflows" / "runs" / "abc12345"
                run_dir.mkdir()
                (run_dir / "state.json").write_text(
                    json.dumps(
                        {
                            "step_results": {
                                "write-adr": {
                                    "status": "completed",
                                    "output": {"stdout": "done"},
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                monitor._poll_once()
            self.assertEqual(monitor.run_id, "abc12345")
            self.assertIn("write-adr", captured.getvalue())
            self.assertIn("done", captured.getvalue())

    def test_preexisting_run_is_not_discovered(self) -> None:
        # A run directory that existed before the wrapper started (e.g. a
        # resumed or concurrent run) must not be mistaken for the current run.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp)
            (state / "workflows" / "runs" / "oldrun01").mkdir()
            captured = io.StringIO()
            with (
                cwd(tmp),
                stdout(captured),
            ):
                monitor = mod.LiveMonitor(state, mod.existing_run_ids(state))
                monitor._poll_once()
            self.assertEqual(monitor.run_id, "")
            self.assertEqual(captured.getvalue(), "")

    def test_explicit_run_id_wins_over_discovery(self) -> None:
        # Once the "Run ID:" line is parsed from stdout it is authoritative;
        # discovery must not replace it with a different directory.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp)
            captured = io.StringIO()
            with (
                cwd(tmp),
                stdout(captured),
            ):
                monitor = mod.LiveMonitor(state, mod.existing_run_ids(state))
                monitor.run_id = "def45678"
                (state / "workflows" / "runs" / "abc12345").mkdir()
                monitor._poll_once()
            self.assertEqual(monitor.run_id, "def45678")
            self.assertEqual(captured.getvalue(), "")
