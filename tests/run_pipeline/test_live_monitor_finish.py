"""Unit tests for LiveMonitor.finish() draining late results and logs."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


class LiveMonitorFinishTest(unittest.TestCase):
    """finish() must drain BOTH late step results and late agent-log lines.

    The tail thread has already stopped when finish() runs, so log lines
    written between the last 0.5s poll tick and process exit would otherwise
    never be printed to the console.
    """

    def test_finish_prints_late_log_lines(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            # The tailer is built as cwd/'${state_dir}/logs'; state_dir
            # defaults to ".workflow" in the rendered template.
            logs_dir = Path(tmp) / ".workflow" / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-executor.jsonl"
            with mock.patch.object(Path, "cwd", return_value=Path(tmp)):
                monitor = mod.LiveMonitor(Path(tmp), set())
                # The "late reply" is appended AFTER the tailer's baseline:
                # only lines written during the run are printed.
                log.write_text(
                    '{"part": {"type": "text", "text": "late reply"}}\n',
                    encoding="utf-8",
                )
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor.finish()
            self.assertIn("late reply", captured.getvalue())

    def test_finish_polls_late_step_results(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "workflows" / "runs" / "abc12345"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "step_results": {
                            "final-step": {
                                "status": "completed",
                                "output": {"stdout": "done"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(Path, "cwd", return_value=Path(tmp)):
                monitor = mod.LiveMonitor(Path(tmp), set())
                monitor.run_id = "abc12345"
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor.finish()
            self.assertIn("final-step", captured.getvalue())
            self.assertIn("done", captured.getvalue())
