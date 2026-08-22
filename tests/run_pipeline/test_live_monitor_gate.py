"""Unit tests for the monitor's gate-open buffering behavior."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import cwd, stdout

from .helpers import load_run_pipeline


class LiveMonitorGateTest(unittest.TestCase):
    """While a human-gate menu is on screen the monitor must buffer step
    results and live status lines instead of printing them, and flush the
    buffer once the engine moves past the gate (or the wrapper stops)."""

    def _prepare(self, tmp: str) -> Path:
        state = Path(tmp)
        run_dir = state / "workflows" / "runs" / "abc12345"
        run_dir.mkdir(parents=True)
        logs_dir = state / ".workflow" / "logs"
        logs_dir.mkdir(parents=True)
        return state

    def _append_log(self, state: Path) -> None:
        # The log line is appended AFTER the monitor is built: the tailer
        # baselines pre-existing files at construction, so this simulates a
        # line written during the run. A step_finish event feeds the live
        # status lines (ADR-0011).
        log = state / ".workflow" / "logs" / "sessions-executor.jsonl"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(
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
                + "\n"
            )

    def _open_state(self, state: Path) -> None:
        (state / "workflows" / "runs" / "abc12345" / "state.json").write_text(
            json.dumps(
                {
                    "current_step_id": "adr-gate",
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

    def test_buffers_events_while_gate_open(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._prepare(tmp)
            self._open_state(state)
            with cwd(state):
                monitor = mod.LiveMonitor(state, set())
                self._append_log(state)
                monitor.run_id = "abc12345"
                monitor.gate.open({"current_step_id": "adr-gate"})
                captured = io.StringIO()
                with stdout(captured):
                    monitor._poll_once()
            # Nothing printed while the gate is open; the step's captured
            # output arrives as a `[harness]` row in the fixed buffer (no
            # separate step-result category anymore), together with the
            # live line and the step-start harness line (ADR-0012,
            # ADR-0016).
            self.assertEqual(captured.getvalue(), "")
            self.assertEqual(monitor.gate._gate_step_id, "adr-gate")
            self.assertEqual(len(monitor._emitter.buffered_fixed), 3)
            self.assertIn("cache 4", monitor._emitter.buffered_fixed[0])
            self.assertIn("[harness]", monitor._emitter.buffered_fixed[1])

    def test_flushes_buffer_when_engine_moves_past_gate(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._prepare(tmp)
            self._open_state(state)
            state_file = state / "workflows" / "runs" / "abc12345" / "state.json"
            with cwd(state):
                monitor = mod.LiveMonitor(state, set())
                self._append_log(state)
                monitor.run_id = "abc12345"
                monitor.gate.open({"current_step_id": "adr-gate"})
                monitor._poll_once()  # buffers events (gate still open)
                # The user answers: the engine moves to the next step.
                state_file.write_text(
                    json.dumps({"current_step_id": "next-step"}), encoding="utf-8"
                )
                captured = io.StringIO()
                with stdout(captured):
                    monitor._poll_once()
            self.assertFalse(monitor.gate.is_open)
            self.assertEqual(monitor._emitter.buffered_fixed, [])
            self.assertIn("done", captured.getvalue())
            self.assertIn("cache 4", captured.getvalue())

    def test_gate_stays_open_while_step_id_unchanged(self) -> None:
        # The user answered invalidly ("Invalid choice. …"): the gate remains
        # open and current_step_id does not move, so buffering must continue.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._prepare(tmp)
            self._open_state(state)
            with cwd(state):
                monitor = mod.LiveMonitor(state, set())
                self._append_log(state)
                monitor.run_id = "abc12345"
                monitor.gate.open({"current_step_id": "adr-gate"})
                captured = io.StringIO()
                with stdout(captured):
                    monitor._poll_once()
                    monitor._poll_once()
            self.assertTrue(monitor.gate.is_open)
            self.assertEqual(captured.getvalue(), "")
            self.assertEqual(monitor.gate._gate_step_id, "adr-gate")

    def test_flushes_buffer_when_wrapper_stops(self) -> None:
        # An aborted/rejected run may leave current_step_id on the gate, so
        # the gate never closes on its own: stopping the wrapper must close
        # it and flush whatever was buffered.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._prepare(tmp)
            self._open_state(state)
            with cwd(state):
                monitor = mod.LiveMonitor(state, set())
                self._append_log(state)
                monitor.run_id = "abc12345"
                monitor.gate.open({"current_step_id": "adr-gate"})
                monitor._poll_once()  # fill the buffer while the gate is open
                monitor.start()
                captured = io.StringIO()
                with stdout(captured):
                    monitor.stop()
                    monitor.join()
            self.assertFalse(monitor.gate.is_open)
            self.assertEqual(monitor._emitter.buffered_fixed, [])
            self.assertIn("done", captured.getvalue())
            self.assertIn("cache 4", captured.getvalue())

    def test_gate_id_captured_synchronously_at_open(self) -> None:
        # Regression: the id must be captured at menu-open time (from the
        # state read by main()) — not on the monitor's next tick, when a
        # fast answer could already have moved current_step_id and the
        # first tick would record the NEXT step's id, leaving the gate open
        # through that whole step.
        mod = load_run_pipeline()
        gate = mod.GateState()
        gate.open({"current_step_id": "adr-gate"})
        self.assertTrue(gate.is_open)
        self.assertEqual(gate._gate_step_id, "adr-gate")
        # The answer lands: the next readable state closes the gate.
        self.assertTrue(gate.update_and_closed({"current_step_id": "next-step"}))
        self.assertFalse(gate.is_open)

    def test_open_without_readable_state_captures_on_first_readable_tick(self) -> None:
        # The open-moment state read can fail (transiently): the id is then
        # captured by update_and_closed() on the first readable tick instead.
        mod = load_run_pipeline()
        gate = mod.GateState()
        gate.open(None)
        self.assertTrue(gate.is_open)
        self.assertIsNone(gate._gate_step_id)
        self.assertFalse(gate.update_and_closed({"current_step_id": "adr-gate"}))
        self.assertEqual(gate._gate_step_id, "adr-gate")
        self.assertFalse(gate.update_and_closed({"current_step_id": "adr-gate"}))
        self.assertTrue(gate.is_open)
        self.assertTrue(gate.update_and_closed({"current_step_id": "next-step"}))
        self.assertFalse(gate.is_open)

    def test_unreadable_state_skips_tick_and_keeps_gate_open(self) -> None:
        # Regression: a failed state.json read (None) must NOT close the
        # gate — "state unreadable" is not "run ended". Closing on it would
        # print straight over the still-open menu (ADR Acceptance Criteria 1).
        mod = load_run_pipeline()
        gate = mod.GateState()
        gate.open({"current_step_id": "adr-gate"})
        self.assertFalse(gate.update_and_closed(None))
        self.assertTrue(gate.is_open)
        self.assertEqual(gate._gate_step_id, "adr-gate")
        # Once the state is readable again with the same id, still open...
        self.assertFalse(gate.update_and_closed({"current_step_id": "adr-gate"}))
        self.assertTrue(gate.is_open)
        # ...and only a readable, differing id closes the gate.
        self.assertTrue(gate.update_and_closed({"current_step_id": "next-step"}))
        self.assertFalse(gate.is_open)

    def test_readable_empty_current_step_id_closes_gate(self) -> None:
        # A READABLE state with an empty/null current_step_id means the
        # engine finished the run — that may close the gate, unlike a failed
        # read (None).
        mod = load_run_pipeline()
        gate = mod.GateState()
        gate.open({"current_step_id": "adr-gate"})
        self.assertTrue(gate.update_and_closed({"current_step_id": None}))
        self.assertFalse(gate.is_open)
