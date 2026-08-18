"""Unit tests for the run statistics block (sessions, export, formatting).

The per-stage latency table tests live in test_latency_table.py (ADR-0009
split the two concerns into run_statistics.py and latency_table.py).
"""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


class RunStatisticsTest(unittest.TestCase):
    """Parsing/summing `opencode export` JSON into the final block."""

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

    def test_read_session_ids_from_current_task_symlink(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1", "executor": "e1"})
            self.assertEqual(
                mod.read_session_ids(state), {"planner": "p1", "executor": "e1"}
            )

    def test_read_session_ids_ignores_missing_empty_and_unreadable(self):
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

    def test_export_session_info_failures_return_none(self):
        mod = load_run_pipeline()
        with mock.patch("subprocess.run", side_effect=OSError("boom")):
            self.assertIsNone(mod.export_session_info("p1"))
        with mock.patch(
            "subprocess.run", return_value=mock.Mock(returncode=1, stdout="")
        ):
            self.assertIsNone(mod.export_session_info("p1"))
        # The export writes only garbage (unparseable both attempts).
        def garbage_run(cmd, stdout=None, **kwargs):
            stdout.write(b"not json")
            return mock.Mock(returncode=0)

        with mock.patch("subprocess.run", side_effect=garbage_run):
            self.assertIsNone(mod.export_session_info("p1"))

    def test_export_retries_once_on_truncated_json(self):
        # opencode (<= 1.18.x) can exit before its piped stdout is fully
        # flushed; the export is retried once before degrading to zeros.
        mod = load_run_pipeline()
        attempts = []

        def fake_run(cmd, stdout=None, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                stdout.write(b'{"info": {"tokens": {"input": 1')
            else:
                payload = {"info": {"tokens": {"input": 5}}}
                stdout.write(json.dumps(payload).encode())
            return mock.Mock(returncode=0)

        with mock.patch("subprocess.run", side_effect=fake_run):
            info = mod.export_session_info("p1")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(info["tokens"]["input"], 5)

    def test_usage_sums_both_roles(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1", "executor": "e1"})

            def fake_run(cmd, stdout=None, **kwargs):
                payloads = {
                    "p1": {
                        "tokens": {
                            "input": 321213,
                            "output": 12345,
                            "reasoning": 5678,
                            "cache": {"read": 9032013, "write": 0},
                        },
                        "cost": 0.02,
                    },
                    "e1": {
                        "tokens": {
                            "input": 5000,
                            "output": 100,
                            "reasoning": 50,
                            "cache": {"read": 100, "write": 5},
                        },
                        "cost": 0.01,
                    },
                }[cmd[-1]]
                stdout.write(json.dumps({"info": payloads}).encode())
                return mock.Mock(returncode=0)

            with mock.patch("subprocess.run", side_effect=fake_run):
                usage = mod.collect_usage(state)
        self.assertEqual(usage["input"], 326213)
        self.assertEqual(usage["output"], 12445)
        self.assertEqual(usage["reasoning"], 5728)
        self.assertEqual(usage["cache_read"], 9032113)
        self.assertEqual(usage["cache_write"], 5)
        self.assertAlmostEqual(usage["cost"], 0.03)

    def test_print_run_statistics_block(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, {"planner": "p1"})

            def fake_run(cmd, stdout=None, **kwargs):
                payload = {
                    "info": {
                        "tokens": {
                            "input": 321213,
                            "output": 12345,
                            "reasoning": 5678,
                            "cache": {"read": 9032013, "write": 0},
                        },
                        "cost": 0.03,
                    }
                }
                stdout.write(json.dumps(payload).encode())
                return mock.Mock(returncode=0)

            captured = io.StringIO()
            with (
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch("sys.stdout", captured),
            ):
                mod.print_run_statistics(state, 6301.0)
        out = captured.getvalue()
        self.assertIn("=== run statistics ===", out)
        self.assertIn("wall time: 01:45:01", out)
        self.assertIn("tokens: input 321 213 · output 12 345 · reasoning 5 678", out)
        self.assertIn("cache: read 9 032 013 · write 0", out)
        self.assertIn("cost: $0.03", out)

    def test_collect_cursor_usage_reuses_the_shared_parser(self):
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

    def test_collect_cursor_usage_counts_step_finish_only_files(self):
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

    def test_malformed_result_event_does_not_suppress_step_finish_tokens(self):
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

    def test_print_run_statistics_degrades_to_zeros(self):
        # No sessions file / no opencode: the block still prints with zeros
        # and the wrapper must not crash.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            captured = io.StringIO()
            with mock.patch("sys.stdout", captured):
                mod.print_run_statistics(Path(tmp), 0.0)
        out = captured.getvalue()
        self.assertIn("=== run statistics ===", out)
        self.assertIn("wall time: 00:00:00", out)
        self.assertIn("tokens: input 0 · output 0 · reasoning 0", out)
        self.assertIn("cache: read 0 · write 0", out)
        self.assertIn("cost: $0.00", out)

    def test_formatting_helpers(self):
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
