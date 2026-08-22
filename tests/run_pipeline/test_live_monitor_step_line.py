"""Unit tests for the non-TTY step-start harness line (ADR-0012)."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


def _step_finish() -> dict[str, object]:
    return {
        "type": "step_finish",
        "part": {
            "tokens": {
                "input": 1,
                "output": 2,
                "reasoning": 3,
                "cache": {"read": 4, "write": 0},
            },
            "cost": 0.01,
        },
    }


class LiveMonitorStepLineTest(unittest.TestCase):
    """On a non-TTY the monitor prints one plain `[hh:mm:ss] [harness]
    [<step> N/M]` line per step change — at most once, after the previous
    step's marker, and not when the step already has agent lines. No
    heartbeat lines ever go into a log."""

    def _prepare(self, tmp: str, step_id: str, step_index: int | None = None) -> None:
        run_dir = Path(tmp) / "workflows" / "runs" / "abc12345"
        run_dir.mkdir(parents=True)
        state: dict[str, object] = {"current_step_id": step_id}
        if step_index is not None:
            state["current_step_index"] = step_index
        state["step_results"] = {}
        (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (Path(tmp) / ".workflow" / "logs").mkdir(parents=True)

    def test_prints_harness_line_once_per_step_change(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            self._prepare(tmp, "study", 0)
            with mock.patch.object(Path, "cwd", return_value=Path(tmp)):
                monitor = mod.LiveMonitor(Path(tmp), set(), step_ids=["study", "research"])
                monitor.run_id = "abc12345"
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor._poll_once()
                    monitor._poll_once()
            out = captured.getvalue()
            # Exactly one line per step change, no heartbeat repeats.
            self.assertEqual(out.count("[harness] [study 1/2]"), 1)
            self.assertEqual(out.count("[harness]"), 1)

    def test_no_harness_line_when_step_already_has_agent_lines(self) -> None:
        # The step's first event lands in the same tick as the step change:
        # the event line replaces the step-start line (ADR-0012).
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            self._prepare(tmp, "study", 0)
            with mock.patch.object(Path, "cwd", return_value=Path(tmp)):
                monitor = mod.LiveMonitor(Path(tmp), set(), step_ids=["study", "research"])
                monitor.run_id = "abc12345"
                log = Path(tmp) / ".workflow" / "logs" / "sessions-planner.jsonl"
                log.write_text(json.dumps(_step_finish()) + "\n", encoding="utf-8")
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor._poll_once()
            out = captured.getvalue()
            self.assertIn("[planner]", out)
            self.assertNotIn("[harness]", out)

    def test_new_step_line_prints_after_previous_marker(self) -> None:
        # The engine advanced current_step_id to the next step: the step
        # start line for it prints AFTER the completed step's marker.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "workflows" / "runs" / "abc12345"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "current_step_id": "research",
                        "current_step_index": 1,
                        "step_results": {
                            "study": {
                                "status": "completed",
                                "output": {"stdout": "done"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (Path(tmp) / ".workflow" / "logs").mkdir(parents=True)
            with mock.patch.object(Path, "cwd", return_value=Path(tmp)):
                monitor = mod.LiveMonitor(Path(tmp), set(), step_ids=["study", "research"])
                monitor.run_id = "abc12345"
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor._poll_once()
            out = captured.getvalue()
            self.assertLess(
                out.index("--- step study (completed) [1/2]"),
                out.index("[harness] [research 2/2]"),
            )
            self.assertEqual(out.count("[harness]"), 1)
