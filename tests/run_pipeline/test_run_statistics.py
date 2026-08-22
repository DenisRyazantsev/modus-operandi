"""Unit tests for the run statistics block (sessions, export, formatting).

The per-stage latency table tests live in test_latency_table.py (ADR-0009
split the two concerns into run_statistics.py and latency_table.py).
"""

import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import env, stdout

from .helpers import export_env, load_run_pipeline


class RunStatisticsTest(unittest.TestCase):
    """Parsing/summing `opencode export` JSON into the final block."""

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

    def test_read_session_ids_from_current_task_symlink(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1", "executor": "e1"})
            self.assertEqual(mod.read_session_ids(state), {"planner": "p1", "executor": "e1"})

    def test_read_session_ids_ignores_missing_empty_and_unreadable(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "", "executor": "e1", "other": "x"})
            self.assertEqual(mod.read_session_ids(state), {"executor": "e1"})
        with tempfile.TemporaryDirectory() as tmp:
            # No tasks/current symlink at all: nothing to read.
            self.assertEqual(mod.read_session_ids(Path(tmp) / "empty"), {})
        with tempfile.TemporaryDirectory() as tmp:
            # No stored sessions: nothing to read.
            broken = self._state(tmp, {}, task_id="broken")
            self.assertEqual(mod.read_session_ids(broken), {})

    def test_export_session_info_failures_return_none(self) -> None:
        mod = load_run_pipeline()
        # opencode not on PATH at all: the real exec fails with OSError.
        with env(export_env(Path(tempfile.mkdtemp()) / "bin", host=False)):
            self.assertIsNone(mod.export_session_info("p1"))
        # A real opencode that exits non-zero: the export degrades to None.
        with (
            tempfile.TemporaryDirectory() as tmp,
            env(export_env(Path(tmp) / "bin", "#!/bin/sh\nexit 1\n")),
        ):
            self.assertIsNone(mod.export_session_info("p1"))
        # The export writes only garbage (unparseable both attempts).
        with (
            tempfile.TemporaryDirectory() as tmp,
            env(export_env(Path(tmp) / "bin", "#!/bin/sh\necho 'not json'\n")),
        ):
            self.assertIsNone(mod.export_session_info("p1"))

    def test_export_retries_once_on_truncated_json(self) -> None:
        # opencode (<= 1.18.x) can exit before its piped stdout is fully
        # flushed; the export is retried once before degrading to zeros. The
        # script is stateful: the first call writes a truncated payload, the
        # second (after the marker file appears) the full one.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            attempts = Path(tmp) / "attempts"
            script = (
                "#!/bin/sh\n"
                'if [ -f "$OPCODE_ATTEMPTS_FILE" ]; then\n'
                '  echo \'{"info": {"tokens": {"input": 5}}}\'\n'
                "else\n"
                '  echo \'{"info": {"tokens": {"input": 1\'\n'
                '  touch "$OPCODE_ATTEMPTS_FILE"\n'
                "fi\n"
            )
            env_overrides = export_env(Path(tmp) / "bin", script)
            env_overrides["OPCODE_ATTEMPTS_FILE"] = str(attempts)
            with env(env_overrides):
                info = mod.export_session_info("p1")
            self.assertTrue(attempts.exists())
        self.assertEqual(info["tokens"]["input"], 5)

    def test_usage_sums_both_roles(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1", "executor": "e1"})
            script = (
                "#!/bin/sh\n"
                'case "$2" in\n'
                '  p1) echo \'{"info": {"tokens": {"input": 321213, "output": 12345,'
                ' "reasoning": 5678, "cache": {"read": 9032013, "write": 0}},'
                ' "cost": 0.02}}\' ;;\n'
                '  e1) echo \'{"info": {"tokens": {"input": 5000, "output": 100,'
                ' "reasoning": 50, "cache": {"read": 100, "write": 5}}, "cost": 0.01}}\' ;;\n'
                "esac\n"
            )
            with env(export_env(Path(tmp) / "bin", script)):
                usage = mod.collect_usage(state)
        self.assertEqual(usage["input"], 326213)
        self.assertEqual(usage["output"], 12445)
        self.assertEqual(usage["reasoning"], 5728)
        self.assertEqual(usage["cache_read"], 9032113)
        self.assertEqual(usage["cache_write"], 5)
        self.assertAlmostEqual(usage["cost"], 0.03)

    def test_malformed_token_fields_degrade_to_zeros(self) -> None:
        # Regression (bug fix): export_session_info validates only that the
        # export parses as JSON with a dict `info`; the token fields are
        # unvalidated. A non-numeric token field must degrade to zero like
        # every other missing-data path — a ValueError/TypeError here would
        # crash the wrapper with a traceback AFTER the run finished
        # (violating "the wrapper never fails here").
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            script = (
                "#!/bin/sh\n"
                'echo \'{"info": {"tokens": {"input": "many", "output": {"nested": 1},'
                ' "reasoning": null, "cache": {"read": "x", "write": 3}},'
                ' "cost": "free"}}\'\n'
            )
            with env(export_env(Path(tmp) / "bin", script)):
                usage = mod.collect_usage(state)
        # Everything non-numeric degrades to zero; the numeric cache_write
        # still counts and the non-numeric cost is ignored like before.
        self.assertEqual(usage["input"], 0)
        self.assertEqual(usage["output"], 0)
        self.assertEqual(usage["reasoning"], 0)
        self.assertEqual(usage["cache_read"], 0)
        self.assertEqual(usage["cache_write"], 3)
        self.assertEqual(usage["cost"], 0.0)

    def test_print_run_statistics_block(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            script = (
                "#!/bin/sh\n"
                'echo \'{"info": {"tokens": {"input": 321213, "output": 12345,'
                ' "reasoning": 5678, "cache": {"read": 9032013, "write": 0}},'
                ' "cost": 0.03}}\'\n'
            )
            captured = io.StringIO()
            with env(export_env(Path(tmp) / "bin", script)), stdout(captured):
                mod.print_run_statistics(state, 6301.0)
        out = captured.getvalue()
        self.assertIn("=== run statistics ===", out)
        self.assertIn("wall time: 01:45:01", out)
        self.assertIn("tokens: input 321 213 · output 12 345 · reasoning 5 678", out)
        self.assertIn("cache: read 9 032 013 · write 0", out)
        self.assertIn("cost: $0.03", out)

    def test_collect_cursor_usage_reuses_the_shared_parser(self) -> None:
        # collect_cursor_usage sums the cursor logs through the shared
        # usage_parser (SRP split): nested usage objects, flat cache names
        # and top-level token fields all accumulate; a malformed event is
        # skipped whole instead of failing the statistics; a step_finish in
        # a file that shows result-style events is ignored (no double
        # count, bug fix).
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            logs_dir = state / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-task-1-executor.jsonl"
            log.write_text(
                "\n".join(
                    json.dumps(event)
                    for event in [
                        {
                            "type": "result",
                            "usage": {"inputTokens": 10, "cacheReadTokens": 7},
                        },
                        {"type": "result", "inputTokens": 5, "outputTokens": 3},
                        {
                            "type": "step_finish",
                            "part": {
                                "tokens": {"input": 100, "cache": {"read": 1}},
                                "cost": 0.5,
                            },
                        },
                        {"type": "result", "usage": {"inputTokens": "abc"}},
                        {"type": "text", "part": {"type": "text", "text": "x"}},
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            usage = mod.run_statistics.collect_cursor_usage(state)
        self.assertEqual(usage["input"], 15)
        self.assertEqual(usage["output"], 3)
        self.assertEqual(usage["cache_read"], 7)
        self.assertEqual(usage["cache_write"], 0)
        # The step_finish fallback was ignored: no cost accumulated.
        self.assertEqual(usage["cost"], 0.0)

    def test_collect_cursor_usage_sees_all_review_loop_iterations(self) -> None:
        # Regression (ADR-0013 bug fix): the per-kind review log is a stable
        # file that run-agent-cursor.sh APPENDS to on every check, so the
        # end-of-run statistics must see every review-fix-loop iteration of a
        # kind — truncating the file on each call would leave only the last
        # iteration's usage in the sum.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            logs_dir = state / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-task-1-planner-fork-srp.jsonl"
            log.write_text(
                "\n".join(
                    json.dumps(event)
                    for event in [
                        # First review-fix-loop iteration of the srp kind.
                        {
                            "type": "result",
                            "usage": {"inputTokens": 10, "cacheReadTokens": 7},
                        },
                        # Second iteration, appended to the same file.
                        {
                            "type": "result",
                            "usage": {"inputTokens": 5, "cacheReadTokens": 3},
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            usage = mod.run_statistics.collect_cursor_usage(state)
        self.assertEqual(usage["input"], 15)
        self.assertEqual(usage["cache_read"], 10)

    def test_collect_cursor_usage_counts_step_finish_only_files(self) -> None:
        # Old cursor builds emit only the opencode-shaped step_finish: a
        # file without any result-style event still counts the fallback
        # (bug fix regression guard).
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            logs_dir = state / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-task-1-executor.jsonl"
            log.write_text(
                json.dumps(
                    {
                        "type": "step_finish",
                        "part": {
                            "tokens": {
                                "input": 10,
                                "output": 2,
                                "reasoning": 1,
                                "cache": {"read": 4, "write": 0},
                            },
                            "cost": 0.03,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            usage = mod.run_statistics.collect_cursor_usage(state)
        self.assertEqual(usage["input"], 10)
        self.assertEqual(usage["output"], 2)
        self.assertEqual(usage["reasoning"], 1)
        self.assertEqual(usage["cache_read"], 4)
        self.assertAlmostEqual(usage["cost"], 0.03)

    def test_malformed_result_event_does_not_suppress_step_finish_tokens(self) -> None:
        # Regression (bug fix): a malformed or unrecognized-shape
        # result-style event is skipped without disabling the fallback —
        # the step_finish tokens of the same file must still count.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})
            logs_dir = state / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-task-1-executor.jsonl"
            log.write_text(
                "\n".join(
                    json.dumps(event)
                    for event in [
                        {"type": "result", "usage": {"inputTokens": "abc"}},
                        {"type": "result", "usage": {"total": 42}},
                        {
                            "type": "step_finish",
                            "part": {
                                "tokens": {
                                    "input": 100,
                                    "output": 2,
                                    "reasoning": 1,
                                    "cache": {"read": 4, "write": 0},
                                },
                                "cost": 0.03,
                            },
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            usage = mod.run_statistics.collect_cursor_usage(state)
        self.assertEqual(usage["input"], 100)
        self.assertEqual(usage["output"], 2)
        self.assertEqual(usage["cache_read"], 4)
        self.assertAlmostEqual(usage["cost"], 0.03)

    def test_print_run_statistics_degrades_to_zeros(self) -> None:
        # No sessions file / no opencode: the block still prints with zeros
        # and the wrapper must not crash. PATH is limited to a bin dir
        # without opencode, so the real exec fails and everything degrades.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            captured = io.StringIO()
            with env(export_env(Path(tmp) / "bin", host=False)), stdout(captured):
                mod.print_run_statistics(Path(tmp), 0.0)
        out = captured.getvalue()
        self.assertIn("=== run statistics ===", out)
        self.assertIn("wall time: 00:00:00", out)
        self.assertIn("tokens: input 0 · output 0 · reasoning 0", out)
        self.assertIn("cache: read 0 · write 0", out)
        self.assertIn("cost: $0.00", out)

    def test_formatting_helpers(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.fmt_thousands(321213), "321 213")
        self.assertEqual(mod.fmt_thousands(0), "0")
        self.assertEqual(mod.fmt_thousands(1000000), "1 000 000")
        self.assertEqual(mod.fmt_duration(0), "00:00:00")
        self.assertEqual(mod.fmt_duration(6301), "01:45:01")
        self.assertEqual(mod.fmt_duration(3661.9), "01:01:01")
        # fmt_minutes is the latency table's compact form (ADR-0011); the
        # statistics block itself keeps HH:MM:SS via fmt_duration.
        self.assertEqual(mod.fmt_minutes(0), "0m")
        self.assertEqual(mod.fmt_minutes(29), "1m")
        self.assertEqual(mod.fmt_minutes(90), "2m")
