"""Unit tests for the log-before-step-marker output order."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


class LiveMonitorLogOrderTest(unittest.TestCase):
    """Agent log lines print BEFORE the step's "--- step X (completed)"
    marker."""

    def test_logs_print_before_step_marker(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            run_dir = state / "workflows" / "runs" / "abc12345"
            run_dir.mkdir(parents=True)
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
            logs_dir = state / ".workflow" / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-executor.jsonl"
            with mock.patch.object(Path, "cwd", return_value=state):
                monitor = mod.LiveMonitor(state, set())
                monitor.run_id = "abc12345"
                # The agent line is appended after the tailer's baseline,
                # like a line written by the finishing step.
                log.write_text(
                    '{"part": {"type": "text", "text": "final agent line"}}\n',
                    encoding="utf-8",
                )
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor._poll_once()
            out = captured.getvalue()
            self.assertLess(
                out.index("final agent line"),
                out.index("--- step write-adr (completed)"),
            )
