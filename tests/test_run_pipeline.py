"""Unit tests for the rendered run-pipeline.py template.

run_pipeline.py.tpl is a string.Template; the tests render it with the
default state_dir and load the result as a module, so the placeholder and
the runtime behavior are both exercised.
"""

import importlib.util
import io
import json
import string
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = (REPO_ROOT / "templates" / "run_pipeline.py.tpl").read_text(encoding="utf-8")


def load_run_pipeline(state_dir: str = ".workflow") -> types.ModuleType:
    rendered = string.Template(_TEMPLATE).substitute(state_dir=state_dir)
    tmpdir = Path(tempfile.mkdtemp(prefix="run_pipeline_test_"))
    path = tmpdir / "run_pipeline.py"
    path.write_text(rendered, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("run_pipeline_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_pipeline_under_test"] = module
    spec.loader.exec_module(module)
    return module


class StepResultPollerTest(unittest.TestCase):
    def _run_dir(self, tmp: str, run_id: str = "abc12345") -> Path:
        run_dir = Path(tmp) / "workflows" / "runs" / run_id
        run_dir.mkdir(parents=True)
        return run_dir

    def test_non_terminal_statuses_never_reported(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run_dir(tmp)
            (run_dir / "state.json").write_text(
                json.dumps(
                    {
                        "step_results": {
                            "running-step": {"status": "running"},
                            "pending-step": {"status": "pending"},
                            "gate": {"status": "completed", "output": {"stdout": "ok"}},
                        }
                    }
                ),
                encoding="utf-8",
            )
            poller = mod.StepResultPoller(Path(tmp), "abc12345")
            first = poller.poll()
            self.assertEqual([step for step, _ in first], ["gate"])
            self.assertEqual(poller.poll(), [])

    def test_step_completing_later_is_reported_once(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run_dir(tmp)
            state_file = run_dir / "state.json"
            state_file.write_text(
                json.dumps({"step_results": {"write-adr": {"status": "pending"}}}),
                encoding="utf-8",
            )
            poller = mod.StepResultPoller(Path(tmp), "abc12345")
            # pending is not a finished event...
            self.assertEqual(poller.poll(), [])
            # ...but once the step terminates it is reported, exactly once.
            state_file.write_text(
                json.dumps({"step_results": {"write-adr": {"status": "failed"}}}),
                encoding="utf-8",
            )
            events = poller.poll()
            self.assertEqual([step for step, _ in events], ["write-adr"])
            self.assertEqual(poller.poll(), [])


class AgentLogTailerTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_run_pipeline()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_unterminated_tail_is_held_back_for_next_poll(self):
        log = self.dir / "x-executor.jsonl"
        complete = '{"part": {"type": "text", "text": "hello"}}\n'
        log.write_text(complete + '{"part": {"type": "text", "text": "work', encoding="utf-8")
        tailer = self.mod.AgentLogTailer(self.dir)
        lines, pos = tailer._read_appended(log)
        # Only the complete line is consumed; the partial JSON is not rendered
        # as garbage.
        self.assertEqual(lines, ['{"part": {"type": "text", "text": "hello"}}'])
        self.assertEqual(pos, len(complete))
        # The writer finishes the line: it is now read as one event.
        log.write_text(
            complete + '{"part": {"type": "text", "text": "work"}}\n', encoding="utf-8"
        )
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, ['{"part": {"type": "text", "text": "work"}}'])
        self.assertEqual(pos, log.stat().st_size)

    def test_wholly_unterminated_chunk_reads_nothing(self):
        log = self.dir / "x-executor.jsonl"
        log.write_text('{"part": {"type": "text", "text": "abc', encoding="utf-8")
        tailer = self.mod.AgentLogTailer(self.dir)
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, [])
        self.assertEqual(pos, 0)

    def test_multibyte_lines_keep_byte_offsets(self):
        # Regression: the offset is a BYTE offset (stat().st_size, fh.seek()),
        # so it must be advanced by the byte length of the consumed chunk.
        # With character-count accounting, the first poll would record
        # pos=11 chars for "Привет мир\n" (20 bytes); the second poll would
        # then fh.seek(11) mid-character and fh.read() would raise
        # UnicodeDecodeError, killing the tailer thread.
        log = self.dir / "x-executor.jsonl"
        first, second = "Привет мир", "вторая строка"
        log.write_text(f"{first}\n", encoding="utf-8")
        tailer = self.mod.AgentLogTailer(self.dir)
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, [first])
        self.assertEqual(pos, len((first + "\n").encode("utf-8")))
        # The file grows; the next poll must not raise UnicodeDecodeError and
        # must read the new line exactly once.
        log.write_text(f"{first}\n{second}\n", encoding="utf-8")
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, [second])
        self.assertEqual(pos, log.stat().st_size)

    def test_unterminated_multibyte_tail_held_back_in_bytes(self):
        log = self.dir / "x-executor.jsonl"
        complete = "Привет мир\n"
        log.write_text(complete + "вторая строка", encoding="utf-8")
        tailer = self.mod.AgentLogTailer(self.dir)
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, ["Привет мир"])
        self.assertEqual(pos, len(complete.encode("utf-8")))
        # The partial line is still re-readable once completed.
        log.write_text(complete + "вторая строка\n", encoding="utf-8")
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, ["вторая строка"])
        self.assertEqual(pos, log.stat().st_size)

    def test_read_error_does_not_skip_chunk(self):
        log = self.dir / "x-executor.jsonl"
        log.write_text("first line\n", encoding="utf-8")
        tailer = self.mod.AgentLogTailer(self.dir)
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, ["first line"])
        log.write_text("first line\nsecond line\n", encoding="utf-8")
        # A transient read failure must not advance the recorded position.
        with mock.patch.object(Path, "open", side_effect=OSError("boom")):
            lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, [])
        self.assertEqual(pos, len("first line\n"))
        # The chunk is retried on the next poll, not permanently skipped.
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, ["second line"])


class RunIdDiscoveryTest(unittest.TestCase):
    """The wrapper cannot learn the run id from stdout until the workflow
    finishes ("Run ID:" prints last), so the monitor must discover the run
    directory created since the wrapper started and poll it live."""

    def _state(self, tmp: str) -> Path:
        runs = Path(tmp) / "workflows" / "runs"
        runs.mkdir(parents=True)
        return Path(tmp)

    def test_new_run_dir_is_discovered_and_polled(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp)
            captured = io.StringIO()
            with (
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("sys.stdout", captured),
            ):
                monitor = mod.LiveMonitor(state, mod.existing_run_ids(state))
                run_dir = state / "workflows" / "runs" / "abc12345"
                run_dir.mkdir()
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
                monitor._poll_once()
            self.assertEqual(monitor.run_id, "abc12345")
            self.assertIn("write-adr", captured.getvalue())
            self.assertIn("done", captured.getvalue())

    def test_preexisting_run_is_not_discovered(self):
        # A run directory that existed before the wrapper started (e.g. a
        # resumed or concurrent run) must not be mistaken for the current run.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp)
            (state / "workflows" / "runs" / "oldrun01").mkdir()
            captured = io.StringIO()
            with (
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("sys.stdout", captured),
            ):
                monitor = mod.LiveMonitor(state, mod.existing_run_ids(state))
                monitor._poll_once()
            self.assertEqual(monitor.run_id, "")
            self.assertEqual(captured.getvalue(), "")

    def test_explicit_run_id_wins_over_discovery(self):
        # Once the "Run ID:" line is parsed from stdout it is authoritative;
        # discovery must not replace it with a different directory.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp)
            captured = io.StringIO()
            with (
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("sys.stdout", captured),
            ):
                monitor = mod.LiveMonitor(state, mod.existing_run_ids(state))
                monitor.run_id = "def45678"
                (state / "workflows" / "runs" / "abc12345").mkdir()
                monitor._poll_once()
            self.assertEqual(monitor.run_id, "def45678")
            self.assertEqual(captured.getvalue(), "")


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
            log.write_text(
                '{"part": {"type": "text", "text": "late reply"}}\n',
                encoding="utf-8",
            )
            with mock.patch.object(Path, "cwd", return_value=Path(tmp)):
                monitor = mod.LiveMonitor(Path(tmp), set())
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


class GateMenuRecognitionTest(unittest.TestCase):
    """The wrapper pauses its own live output only while a human-gate menu
    window is on screen; recognizing the window's first line is a pure
    string predicate."""

    def test_recognizes_menu_opener_line(self):
        mod = load_run_pipeline()
        self.assertTrue(mod.is_gate_menu_opener("┌─ Gate ───────────"))
        self.assertTrue(mod.is_gate_menu_opener("  ┌─ Gate ···"))  # leading spaces
        self.assertTrue(mod.is_gate_menu_opener("┌─ Gate"))

    def test_rejects_other_lines(self):
        mod = load_run_pipeline()
        self.assertFalse(mod.is_gate_menu_opener(""))
        self.assertFalse(mod.is_gate_menu_opener("writing the ADR..."))
        self.assertFalse(mod.is_gate_menu_opener("│ 1. approve"))  # menu body line
        self.assertFalse(mod.is_gate_menu_opener("┌─ Not a gate"))


class RenderLogEventFilterTest(unittest.TestCase):
    """From the agent logs only text parts with a non-empty payload are
    printed; marker events (step-start/step-finish) and empty text parts are
    dropped entirely — they carry no information and only noise up the
    output."""

    def test_text_part_with_payload_is_shown(self):
        mod = load_run_pipeline()
        role, text = mod.render_log_event(
            "executor", '{"part": {"type": "text", "text": "writing ADR"}}'
        )
        self.assertEqual((role, text), ("executor", "writing ADR"))

    def test_marker_events_and_empty_text_are_dropped(self):
        mod = load_run_pipeline()
        for line in (
            '{"type": "step-start", "part": {"type": "step-start"}}',
            '{"type": "step-finish", "part": {"type": "step-finish"}}',
            '{"type": "text", "part": {"type": "text", "text": ""}}',
            '{"type": "text", "part": {"type": "text"}}',
        ):
            self.assertEqual(mod.render_log_event("executor", line)[1], "")

    def test_non_json_line_passes_through_raw(self):
        mod = load_run_pipeline()
        role, text = mod.render_log_event("executor", "plain line")
        self.assertEqual(text, "plain line")


class LiveMonitorGateTest(unittest.TestCase):
    """While a human-gate menu is on screen the monitor must buffer step
    results and agent-log lines instead of printing them, and flush the
    buffer once the engine moves past the gate (or the wrapper stops)."""

    def _prepare(self, tmp: str) -> Path:
        state = Path(tmp)
        run_dir = state / "workflows" / "runs" / "abc12345"
        run_dir.mkdir(parents=True)
        logs_dir = state / ".workflow" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "sessions-executor.jsonl").write_text(
            '{"part": {"type": "text", "text": "agent work"}}\n', encoding="utf-8"
        )
        return state

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

    def test_buffers_events_while_gate_open(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._prepare(tmp)
            self._open_state(state)
            with mock.patch.object(Path, "cwd", return_value=state):
                monitor = mod.LiveMonitor(state, set())
                monitor.run_id = "abc12345"
                monitor.gate.open({"current_step_id": "adr-gate"})
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor._poll_once()
            # Nothing printed while the gate is open; the step result, the
            # gate step id and the log line are all captured instead.
            self.assertEqual(captured.getvalue(), "")
            self.assertEqual(monitor.gate._gate_step_id, "adr-gate")
            self.assertEqual(len(monitor._buffered_steps), 1)
            self.assertEqual(monitor._buffered_logs, [("executor", "agent work")])

    def test_flushes_buffer_when_engine_moves_past_gate(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._prepare(tmp)
            self._open_state(state)
            state_file = state / "workflows" / "runs" / "abc12345" / "state.json"
            with mock.patch.object(Path, "cwd", return_value=state):
                monitor = mod.LiveMonitor(state, set())
                monitor.run_id = "abc12345"
                monitor.gate.open({"current_step_id": "adr-gate"})
                monitor._poll_once()  # buffers events (gate still open)
                # The user answers: the engine moves to the next step.
                state_file.write_text(
                    json.dumps({"current_step_id": "next-step"}), encoding="utf-8"
                )
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor._poll_once()
            self.assertFalse(monitor.gate.is_open)
            self.assertEqual(monitor._buffered_steps, [])
            self.assertEqual(monitor._buffered_logs, [])
            self.assertIn("done", captured.getvalue())
            self.assertIn("agent work", captured.getvalue())

    def test_gate_stays_open_while_step_id_unchanged(self):
        # The user answered invalidly ("Invalid choice. …"): the gate remains
        # open and current_step_id does not move, so buffering must continue.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._prepare(tmp)
            self._open_state(state)
            with mock.patch.object(Path, "cwd", return_value=state):
                monitor = mod.LiveMonitor(state, set())
                monitor.run_id = "abc12345"
                monitor.gate.open({"current_step_id": "adr-gate"})
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor._poll_once()
                    monitor._poll_once()
            self.assertTrue(monitor.gate.is_open)
            self.assertEqual(captured.getvalue(), "")
            self.assertEqual(monitor.gate._gate_step_id, "adr-gate")

    def test_flushes_buffer_when_wrapper_stops(self):
        # An aborted/rejected run may leave current_step_id on the gate, so
        # the gate never closes on its own: stopping the wrapper must close
        # it and flush whatever was buffered.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = self._prepare(tmp)
            self._open_state(state)
            with mock.patch.object(Path, "cwd", return_value=state):
                monitor = mod.LiveMonitor(state, set())
                monitor.run_id = "abc12345"
                monitor.gate.open({"current_step_id": "adr-gate"})
                monitor._poll_once()  # fill the buffer while the gate is open
                monitor.start()
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor.stop()
                    monitor.join()
            self.assertFalse(monitor.gate.is_open)
            self.assertEqual(monitor._buffered_steps, [])
            self.assertEqual(monitor._buffered_logs, [])
            self.assertIn("done", captured.getvalue())
            self.assertIn("agent work", captured.getvalue())

    def test_gate_id_captured_synchronously_at_open(self):
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
        self.assertTrue(gate.update({"current_step_id": "next-step"}))
        self.assertFalse(gate.is_open)

    def test_open_without_readable_state_captures_on_first_readable_tick(self):
        # The open-moment state read can fail (transiently): the id is then
        # captured by update() on the first readable tick instead.
        mod = load_run_pipeline()
        gate = mod.GateState()
        gate.open(None)
        self.assertTrue(gate.is_open)
        self.assertIsNone(gate._gate_step_id)
        self.assertFalse(gate.update({"current_step_id": "adr-gate"}))
        self.assertEqual(gate._gate_step_id, "adr-gate")
        self.assertFalse(gate.update({"current_step_id": "adr-gate"}))
        self.assertTrue(gate.is_open)
        self.assertTrue(gate.update({"current_step_id": "next-step"}))
        self.assertFalse(gate.is_open)

    def test_unreadable_state_skips_tick_and_keeps_gate_open(self):
        # Regression: a failed state.json read (None) must NOT close the
        # gate — "state unreadable" is not "run ended". Closing on it would
        # print straight over the still-open menu (ADR Acceptance Criteria 1).
        mod = load_run_pipeline()
        gate = mod.GateState()
        gate.open({"current_step_id": "adr-gate"})
        self.assertFalse(gate.update(None))
        self.assertTrue(gate.is_open)
        self.assertEqual(gate._gate_step_id, "adr-gate")
        # Once the state is readable again with the same id, still open...
        self.assertFalse(gate.update({"current_step_id": "adr-gate"}))
        self.assertTrue(gate.is_open)
        # ...and only a readable, differing id closes the gate.
        self.assertTrue(gate.update({"current_step_id": "next-step"}))
        self.assertFalse(gate.is_open)

    def test_readable_empty_current_step_id_closes_gate(self):
        # A READABLE state with an empty/null current_step_id means the
        # engine finished the run — that may close the gate, unlike a failed
        # read (None).
        mod = load_run_pipeline()
        gate = mod.GateState()
        gate.open({"current_step_id": "adr-gate"})
        self.assertTrue(gate.update({"current_step_id": None}))
        self.assertFalse(gate.is_open)


if __name__ == "__main__":
    unittest.main()
