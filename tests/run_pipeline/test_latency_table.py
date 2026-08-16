"""Unit tests for the per-stage latency table (latency_table.py, ADR-0009)."""

import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


def _ms(iso: str) -> int:
    return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)


class LatencyTableTest(unittest.TestCase):
    """Parsing the engine's log.jsonl into per-stage durations and the
    agent-vs-shell breakdown, with graceful degradation on missing data."""

    def _state(self, tmp: str, sessions: dict, task_id: str = "task-1") -> Path:
        state = Path(tmp) / ".workflow"
        tasks = state / "tasks"
        tasks.mkdir(parents=True, exist_ok=True)
        target = tasks / task_id
        target.mkdir(exist_ok=True)
        current = tasks / "current"
        if not current.exists():
            current.symlink_to(task_id, target_is_directory=True)
        (state / f"sessions-{task_id}.json").write_text(
            json.dumps(sessions), encoding="utf-8"
        )
        return state

    def _run_dir(self, tmp: str, with_state: bool = True) -> Path:
        run_dir = Path(tmp) / ".specify" / "workflows" / "runs" / "abc123"
        run_dir.mkdir(parents=True)

        def iso(offset_s: int) -> str:
            base = datetime.datetime(2026, 8, 16, 10, 0, 0, tzinfo=datetime.UTC)
            return (base + datetime.timedelta(seconds=offset_s)).isoformat()

        events = [
            ("pending-kinds", 0, 1, "completed"),
            ("review-fan", 1, 6, "completed"),
            ("review-fan:check:0", 2, 5, "completed"),
            ("review-fan:check:1", 2, 6, "completed"),
            ("merge-reports", 6, 7, "failed"),
            ("fix-all", 7, 30, "completed"),
        ]
        lines = []
        for step_id, start, end, status in events:
            lines.append(
                json.dumps(
                    {"event": "step_started", "step_id": step_id, "timestamp": iso(start)}
                )
            )
            lines.append(
                json.dumps(
                    {
                        "event": "step_completed",
                        "step_id": step_id,
                        "status": status,
                        "timestamp": iso(end),
                    }
                )
            )
        (run_dir / "log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if with_state:
            # The single-iteration pending output maps the fan-out items to
            # the four kinds (first iteration always reviews all of them).
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "step_results": {
                            "pending-kinds": {
                                "output": {"stdout": '["srp", "bugs", "review", "comment"]'}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
        return run_dir

    def _agent_logs(self, state: Path) -> None:
        # Agent events inside the fix-all window (07..30s): 10s of agent
        # activity, the rest of the 23s stage is shell overhead.
        logs = state / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "sessions-task-1-planner-fork-11.jsonl").write_text(
            json.dumps(
                {"type": "step_start", "timestamp": _ms("2026-08-16T10:00:10+00:00")}
            )
            + "\n"
            + json.dumps(
                {"type": "step_finish", "timestamp": _ms("2026-08-16T10:00:20+00:00")}
            )
            + "\n",
            encoding="utf-8",
        )

    def test_latency_table_lists_stages_with_agent_shell_breakdown(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = self._run_dir(tmp)
            self._agent_logs(state)
            captured = io.StringIO()
            with (
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
                mock.patch("sys.stdout", captured),
            ):
                mod.print_run_statistics(state, 30.0, run_dir)
        out = captured.getvalue()
        self.assertIn("=== latency by stage ===", out)
        self.assertIn("pending-kinds", out)
        # Duration column: fix-all spans 23s (07 -> 30).
        self.assertIn("fix-all", out)
        # Agent vs shell breakdown: 10s agent activity inside the 23s stage.
        self.assertIn("00:00:10", out)
        self.assertIn("00:00:13", out)

    def test_latency_table_parallel_checks_block(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = self._run_dir(tmp)
            captured = io.StringIO()
            with (
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
                mock.patch("sys.stdout", captured),
            ):
                mod.print_run_statistics(state, 30.0, run_dir)
        out = captured.getvalue()
        self.assertIn("parallel checks (fan-out):", out)
        self.assertIn("iteration 1:", out)
        # The iteration-1 items map positionally to the four kinds.
        self.assertIn("srp", out)
        self.assertIn("bugs", out)
        # srp ran 3s (02 -> 05), bugs 4s (02 -> 06); fan-out wall is 4s.
        self.assertIn("fan-out wall", out)
        self.assertIn("00:00:04", out)

    def test_latency_table_fan_out_wall_is_per_iteration(self):
        # Bug fix: the fan-out wall must be computed per retry-loop iteration,
        # not as the min(start)..max(end) span across ALL iterations — that
        # would stretch from the first check of iteration 1 to the last check
        # of the last iteration and swallow the merge/fix steps in between.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = Path(tmp) / ".specify" / "workflows" / "runs" / "abc123"
            run_dir.mkdir(parents=True)

            def iso(offset_s: int) -> str:
                base = datetime.datetime(2026, 8, 16, 10, 0, 0, tzinfo=datetime.UTC)
                return (base + datetime.timedelta(seconds=offset_s)).isoformat()

            events = [
                # iteration 1: four parallel checks (02..07)
                ("review-fan:check:0", 2, 5, "completed"),
                ("review-fan:check:1", 2, 6, "completed"),
                ("review-fan:check:2", 3, 4, "completed"),
                ("review-fan:check:3", 3, 7, "completed"),
                # merge + fix between the iterations
                ("merge-reports", 7, 8, "failed"),
                ("fix-all", 8, 20, "completed"),
                # iteration 2: two re-checked kinds (21..27)
                ("review-fix-loop:review-fan:1:check:0", 21, 27, "completed"),
                ("review-fix-loop:review-fan:1:check:1", 22, 26, "completed"),
            ]
            lines = []
            for step_id, start, end, status in events:
                lines.append(
                    json.dumps(
                        {"event": "step_started", "step_id": step_id, "timestamp": iso(start)}
                    )
                )
                lines.append(
                    json.dumps(
                        {
                            "event": "step_completed",
                            "step_id": step_id,
                            "status": status,
                            "timestamp": iso(end),
                        }
                    )
                )
            (run_dir / "log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            # The iteration-2 pending maps its items to the re-reviewed kinds.
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "step_results": {
                            "review-fix-loop:pending-kinds:1": {
                                "output": {"stdout": '["review", "comment"]'}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            captured = io.StringIO()
            with (
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
                mock.patch("sys.stdout", captured),
            ):
                mod.print_run_statistics(state, 30.0, run_dir)
        out = captured.getvalue()
        # Both iterations are reported as separate groups with their own wall.
        self.assertIn("iteration 1:", out)
        self.assertIn("iteration 2:", out)
        self.assertEqual(out.count("fan-out wall"), 2)
        # iter 1 wall = 02..07 = 5s; iter 2 wall = 21..27 = 6s. The buggy
        # all-items span would be 2..27 = 25s.
        self.assertIn("00:00:05", out)
        self.assertIn("00:00:06", out)
        self.assertNotIn("00:00:25", out)
        # The iteration-2 kinds come from the pending step's output.
        self.assertIn("review", out)
        self.assertIn("comment", out)

    def test_latency_table_degrades_to_empty_without_run_dir(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            captured = io.StringIO()
            with (
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
                mock.patch("sys.stdout", captured),
            ):
                mod.print_run_statistics(state, 30.0, None)
        out = captured.getvalue()
        self.assertIn("=== run statistics ===", out)
        self.assertNotIn("=== latency by stage ===", out)

    def test_latency_table_degrades_when_log_jsonl_missing(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = Path(tmp) / ".specify" / "workflows" / "runs" / "abc123"
            run_dir.mkdir(parents=True)  # exists, but no log.jsonl
            captured = io.StringIO()
            with (
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
                mock.patch("sys.stdout", captured),
            ):
                mod.print_run_statistics(state, 30.0, run_dir)
        self.assertNotIn("=== latency by stage ===", captured.getvalue())

    def test_latency_table_module_importable_directly(self):
        # The module is a standalone concern (ADR-0009 SRP finding): it must
        # be importable on its own, not only through run_statistics.py.
        mod = load_run_pipeline()
        self.assertTrue(hasattr(mod, "latency_table"))
        self.assertTrue(callable(mod.latency_table.print_latency_table))
