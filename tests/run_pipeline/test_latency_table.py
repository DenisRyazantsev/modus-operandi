"""Unit tests for the per-stage latency table (latency_table.py, ADR-0009/0011)."""

import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import env, stdout

from .helpers import export_env, load_run_pipeline


def _ms(iso: str) -> int:
    return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)


class LatencyTableTest(unittest.TestCase):
    """Parsing the engine's log.jsonl into per-stage durations (whole
    minutes, fmt_minutes) with the percent share of the total wall time,
    and the agent-vs-shell breakdown, with graceful degradation on missing
    data."""

    def _state(self, tmp: str, sessions: dict[str, object], task_id: str = "task-1") -> Path:
        state = Path(tmp) / ".workflow"
        tasks = state / "tasks"
        tasks.mkdir(parents=True, exist_ok=True)
        target = tasks / task_id
        target.mkdir(exist_ok=True)
        current = tasks / "current"
        if not current.exists():
            current.symlink_to(task_id, target_is_directory=True)
        (state / f"sessions-{task_id}.json").write_text(json.dumps(sessions), encoding="utf-8")
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
                json.dumps({"event": "step_started", "step_id": step_id, "timestamp": iso(start)})
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
            json.dumps({"type": "step_start", "timestamp": _ms("2026-08-16T10:00:10+00:00")})
            + "\n"
            + json.dumps({"type": "step_finish", "timestamp": _ms("2026-08-16T10:00:20+00:00")})
            + "\n",
            encoding="utf-8",
        )

    def test_latency_table_lists_stages_with_agent_shell_breakdown(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = self._run_dir(tmp)
            self._agent_logs(state)
            captured = io.StringIO()
            with (
                env(export_env(Path(tmp) / "bin")),
                stdout(captured),
            ):
                mod.print_run_statistics(state, 30.0, run_dir)
        out = captured.getvalue()
        self.assertIn("=== latency by stage ===", out)
        self.assertIn("pending-kinds", out)
        self.assertIn("fix-all", out)
        # Durations are whole minutes: fix-all spans 23s -> 1m.
        self.assertIn("1m", out)
        # Percent column: fix-all = 23s of the run's wall time (records
        # span 0..30s) -> 76.7%. The denominator is the span, not the sum
        # of the row durations (nested/parallel rows overlap).
        self.assertIn("76.7%", out)

    def test_latency_table_parallel_checks_block(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = self._run_dir(tmp)
            captured = io.StringIO()
            with (
                env(export_env(Path(tmp) / "bin")),
                stdout(captured),
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
        # Percentages against the run's wall time (records span 0..30s):
        # srp = 10.0%, wall = 13.3%.
        self.assertIn("10.0%", out)
        self.assertIn("13.3%", out)

    def test_latency_table_fan_out_wall_is_per_iteration(self) -> None:
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
                env(export_env(Path(tmp) / "bin")),
                stdout(captured),
            ):
                mod.print_run_statistics(state, 30.0, run_dir)
        out = captured.getvalue()
        # Both iterations are reported as separate groups with their own wall.
        self.assertIn("iteration 1:", out)
        self.assertIn("iteration 2:", out)
        self.assertEqual(out.count("fan-out wall"), 2)
        # iter 1 wall = 02..07 = 5s; iter 2 wall = 21..27 = 6s. The buggy
        # all-items span would be 2..27 = 25s (2.6% of the 945s total would
        # never match — the percents pin the spans instead).
        # The run's wall time is the records' span 2..27 = 25s (NOT the
        # sum of the row durations — nested/parallel rows overlap): iter 1
        # wall 5s = 20.0%, iter 2 wall 6s = 24.0%.
        self.assertIn("20.0%", out)
        self.assertIn("24.0%", out)
        self.assertNotIn("100.0%", out)  # the buggy all-items span = 25s
        # The iteration-2 kinds come from the pending step's output.
        self.assertIn("review", out)
        self.assertIn("comment", out)

    def test_latency_table_distinct_minute_durations(self) -> None:
        # Minutes-scale stages produce distinct fmt_minutes values and
        # percents (90s -> 2m, 150s -> 3m, 60s -> 1m of a 300s total).
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = Path(tmp) / ".specify" / "workflows" / "runs" / "abc123"
            run_dir.mkdir(parents=True)

            def iso(offset_s: int) -> str:
                base = datetime.datetime(2026, 8, 16, 10, 0, 0, tzinfo=datetime.UTC)
                return (base + datetime.timedelta(seconds=offset_s)).isoformat()

            events = [
                ("short", 0, 60, "completed"),
                ("medium", 60, 150, "completed"),
                ("long", 150, 300, "completed"),
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
            captured = io.StringIO()
            with (
                env(export_env(Path(tmp) / "bin")),
                stdout(captured),
            ):
                mod.print_run_statistics(state, 300.0, run_dir)
        out = captured.getvalue()
        self.assertIn("1m", out)
        self.assertIn("2m", out)
        self.assertIn("3m", out)
        # 60s/300s = 20.0%, 90s/300s = 30.0%, 150s/300s = 50.0%.
        self.assertIn("20.0%", out)
        self.assertIn("30.0%", out)
        self.assertIn("50.0%", out)

    def test_percent_denominator_is_run_wall_time_not_row_sum(self) -> None:
        # Bug fix: the percent base is the run's wall time (first start ..
        # last end across ALL records), NOT the sum of the row durations —
        # a parent loop step and its nested iteration steps overlap, so
        # summing the rows inflates the denominator and shrinks every
        # percent. Here the rows sum to 140s but the run spans 100s: the
        # child's 20s must read 20.0%, not 14.3%.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = Path(tmp) / ".specify" / "workflows" / "runs" / "abc123"
            run_dir.mkdir(parents=True)

            def iso(offset_s: int) -> str:
                base = datetime.datetime(2026, 8, 16, 10, 0, 0, tzinfo=datetime.UTC)
                return (base + datetime.timedelta(seconds=offset_s)).isoformat()

            events = [
                ("motivation-loop", 0, 100, "completed"),
                ("motivation-loop:motivation-gate:1", 10, 30, "completed"),
                ("motivation-loop:motivation-gate:2", 40, 60, "completed"),
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
            captured = io.StringIO()
            with (
                env(export_env(Path(tmp) / "bin")),
                stdout(captured),
            ):
                mod.print_run_statistics(state, 100.0, run_dir)
        out = captured.getvalue()
        self.assertIn("20.0%", out)  # child 20s of the 100s span
        self.assertIn("100.0%", out)  # the parent loop covers the whole span
        self.assertNotIn("14.3%", out)  # 20s of the inflated 140s row sum
        # The trailing note names the base so the column is not mistaken
        # for a partition of the run.
        self.assertIn("percentages are shares of the run's wall time", out)

    def test_latency_table_degrades_to_empty_without_run_dir(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            captured = io.StringIO()
            with (
                env(export_env(Path(tmp) / "bin")),
                stdout(captured),
            ):
                mod.print_run_statistics(state, 30.0, None)
        out = captured.getvalue()
        self.assertIn("=== run statistics ===", out)
        self.assertNotIn("=== latency by stage ===", out)

    def test_latency_table_degrades_when_log_jsonl_missing(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            run_dir = Path(tmp) / ".specify" / "workflows" / "runs" / "abc123"
            run_dir.mkdir(parents=True)  # exists, but no log.jsonl
            captured = io.StringIO()
            with (
                env(export_env(Path(tmp) / "bin")),
                stdout(captured),
            ):
                mod.print_run_statistics(state, 30.0, run_dir)
        self.assertNotIn("=== latency by stage ===", captured.getvalue())
