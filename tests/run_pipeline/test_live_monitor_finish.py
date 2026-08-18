"""Unit tests for LiveMonitor.finish() draining late results and logs."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


def step_finish(input=1, output=2, reasoning=3, cache_read=4, cost=0.01):
    return {
        "type": "step_finish",
        "part": {
            "type": "step-finish",
            "tokens": {
                "input": input,
                "output": output,
                "reasoning": reasoning,
                "cache": {"read": cache_read, "write": 0},
            },
            "cost": cost,
        },
    }


class LiveMonitorFinishTest(unittest.TestCase):
    """finish() must drain BOTH late step results and late agent-log events.

    The tail thread has already stopped when finish() runs, so events
    written between the last 0.5s poll tick and process exit would otherwise
    never reach the live status lines (ADR-0011).
    """

    def test_finish_prints_late_step_finish_line(self):
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
                # only lines written during the run are counted.
                log.write_text(
                    json.dumps(step_finish()) + "\n",
                    encoding="utf-8",
                )
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor.finish()
            # Non-TTY (StringIO): one plain line per step_finish event.
            out = captured.getvalue()
            self.assertIn("[executor]", out)
            self.assertIn("cache 4", out)
            self.assertIn("price $0.01", out)

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
