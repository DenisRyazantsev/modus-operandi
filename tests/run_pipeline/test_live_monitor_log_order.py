"""Unit tests for the agent-row-before-step-output-rows order."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import cwd, stdout

from .helpers import load_run_pipeline


class LiveMonitorLogOrderTest(unittest.TestCase):
    """The finishing step's live status row is fixed (printed as history)
    BEFORE the step's captured output rows (ADR-0016)."""

    def test_agent_line_prints_before_step_output_rows(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            run_dir = state / "workflows" / "runs" / "abc12345"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "current_step_id": "write-adr",
                        "step_results": {
                            "write-adr": {
                                "status": "completed",
                                "output": {"stdout": "done"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            logs_dir = state / ".workflow" / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-planner.jsonl"
            with cwd(state):
                monitor = mod.LiveMonitor(state, set())
                monitor.run_id = "abc12345"
                # The agent event is appended after the tailer's baseline,
                # like an event written by the finishing step.
                log.write_text(
                    json.dumps(
                        {
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
                    )
                    + "\n",
                    encoding="utf-8",
                )
                captured = io.StringIO()
                with stdout(captured):
                    monitor._poll_once()
            out = captured.getvalue()
            # The agent row (with the token section) prints before the
            # step's captured stdout row.
            self.assertLess(
                out.index("cache 4"),
                out.index("done"),
            )

    def test_fixed_line_prints_once_no_stale_block(self) -> None:
        # The fixed line is the block's last state: it prints plainly as
        # history and must not reappear as a (stale) live block after the
        # step's captured rows — the count of its content is exactly one.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            run_dir = state / "workflows" / "runs" / "abc12345"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "current_step_id": "write-adr",
                        "step_results": {
                            "write-adr": {
                                "status": "completed",
                                "output": {"stdout": "done"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            logs_dir = state / ".workflow" / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-planner.jsonl"
            with cwd(state):
                monitor = mod.LiveMonitor(state, set(), step_ids=["study", "write-adr"])
                monitor.run_id = "abc12345"
                log.write_text(
                    json.dumps(
                        {
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
                    )
                    + "\n",
                    encoding="utf-8",
                )
                captured = io.StringIO()
                with stdout(captured):
                    monitor._poll_once()
            out = captured.getvalue()
            # The agent row prints before the step's captured output rows.
            self.assertLess(
                out.index("cache 4"),
                out.index("done"),
            )
            self.assertEqual(out.count("cache 4"), 1)

    def test_unreadable_current_step_index_does_not_crash(self) -> None:
        # A non-numeric current_step_index in state.json must not crash the
        # monitor thread (bug fix): the live line degrades to no N/M.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            run_dir = state / "workflows" / "runs" / "abc12345"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "current_step_id": "write-adr",
                        "current_step_index": "oops",
                        "step_results": {},
                    }
                ),
                encoding="utf-8",
            )
            logs_dir = state / ".workflow" / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-planner.jsonl"
            with cwd(state):
                monitor = mod.LiveMonitor(state, set(), step_ids=["write-adr"])
                monitor.run_id = "abc12345"
                log.write_text(
                    json.dumps(
                        {
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
                    )
                    + "\n",
                    encoding="utf-8",
                )
                captured = io.StringIO()
                with stdout(captured):
                    monitor._poll_once()
            out = captured.getvalue()
            self.assertIn("[planner]", out)
            self.assertIn("[write-adr]", out)
            self.assertNotIn("1/1", out)
