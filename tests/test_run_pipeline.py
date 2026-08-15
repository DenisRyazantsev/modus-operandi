"""Unit tests for the rendered run-pipeline.py template.

run_pipeline.py.tpl is a string.Template; the tests render it with the
default state_dir and load the result as a module, so the placeholder and
the runtime behavior are both exercised.
"""

import contextlib
import importlib.util
import io
import json
import os
import pty
import string
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = (REPO_ROOT / "templates" / "run_pipeline.py.tpl").read_text(encoding="utf-8")


def load_run_pipeline(
    state_dir: str = ".workflow", sound_path: str = "/nonexistent/victory.wav"
) -> types.ModuleType:
    rendered = string.Template(_TEMPLATE).substitute(
        state_dir=state_dir, sound_path=sound_path
    )
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
        # The tailer is constructed BEFORE the file exists so the baseline
        # (which snapshots pre-existing files) does not consume it.
        tailer = self.mod.AgentLogTailer(self.dir)
        log.write_text(complete + '{"part": {"type": "text", "text": "work', encoding="utf-8")
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
        tailer = self.mod.AgentLogTailer(self.dir)
        log.write_text('{"part": {"type": "text", "text": "abc', encoding="utf-8")
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
        tailer = self.mod.AgentLogTailer(self.dir)
        log.write_text(f"{first}\n", encoding="utf-8")
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
        tailer = self.mod.AgentLogTailer(self.dir)
        log.write_text(complete + "вторая строка", encoding="utf-8")
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
        tailer = self.mod.AgentLogTailer(self.dir)
        log.write_text("first line\n", encoding="utf-8")
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

    def test_preexisting_log_content_is_skipped(self):
        # Files that existed before the wrapper started were written by
        # previous runs (the logs dir is never cleaned): the tailer baselines
        # their sizes at construction, so only lines appended during the
        # current run are printed.
        log = self.dir / "sessions-executor.jsonl"
        log.write_text(
            '{"part": {"type": "text", "text": "old"}}\n', encoding="utf-8"
        )
        tailer = self.mod.AgentLogTailer(self.dir)
        self.assertEqual(tailer.tail(), [])
        # The current run appends a line: only that line is shown.
        log.write_text(
            '{"part": {"type": "text", "text": "old"}}\n'
            '{"part": {"type": "text", "text": "new"}}\n',
            encoding="utf-8",
        )
        self.assertEqual(tailer.tail(), [("executor", "new")])

    def test_new_file_after_baseline_starts_from_zero(self):
        # A log file created after the baseline (by the current run) is not
        # in the snapshot and starts at offset 0.
        tailer = self.mod.AgentLogTailer(self.dir)
        log = self.dir / "sessions-planner.jsonl"
        log.write_text(
            '{"part": {"type": "text", "text": "fresh"}}\n', encoding="utf-8"
        )
        self.assertEqual(tailer.tail(), [("planner", "fresh")])


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
        return state

    def _append_log(self, state: Path, text: str = "agent work") -> None:
        # The log line is appended AFTER the monitor is built: the tailer
        # baselines pre-existing files at construction, so this simulates a
        # line written during the run.
        log = state / ".workflow" / "logs" / "sessions-executor.jsonl"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"part": {"type": "text", "text": text}}) + "\n")

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
                self._append_log(state)
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
                self._append_log(state)
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
                self._append_log(state)
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
                self._append_log(state)
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


class NotifyTest(unittest.TestCase):
    """One victory.wav for every event, played non-blockingly, with quiet
    degradation when the file, a system player or a TTY is unavailable."""

    def _sound(self, tmp: str) -> Path:
        wav = Path(tmp) / "victory.wav"
        wav.write_bytes(b"RIFF")
        return wav

    def test_plays_sound_via_system_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = self._sound(tmp)
            mod = load_run_pipeline(sound_path=str(wav))
            with (
                mock.patch("sys.stdout.isatty", return_value=True),
                mock.patch("subprocess.Popen") as popen,
                mock.patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"),
            ):
                mod.notify()
            popen.assert_called_once()
            cmd = popen.call_args.args[0]
            self.assertEqual(cmd[-1], str(wav))
            # The system player: afplay (macOS) or paplay/aplay (Linux).
            self.assertTrue(cmd[0].endswith(("afplay", "paplay", "aplay")))

    def test_skips_when_not_a_tty(self):
        mod = load_run_pipeline()
        with (
            mock.patch("sys.stdout.isatty", return_value=False),
            mock.patch("subprocess.Popen") as popen,
        ):
            mod.notify()
        popen.assert_not_called()

    def test_skips_when_sound_file_missing(self):
        mod = load_run_pipeline(sound_path="/nonexistent/victory.wav")
        with (
            mock.patch("sys.stdout.isatty", return_value=True),
            mock.patch("subprocess.Popen") as popen,
        ):
            mod.notify()
        popen.assert_not_called()

    def test_skips_when_no_player_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = self._sound(tmp)
            mod = load_run_pipeline(sound_path=str(wav))
            with (
                mock.patch("sys.stdout.isatty", return_value=True),
                mock.patch("shutil.which", return_value=None),
                mock.patch("subprocess.Popen") as popen,
            ):
                mod.notify()
            popen.assert_not_called()


class SoundTimingTest(unittest.TestCase):
    """The sound fires at the gate opening, on success and on failure alike —
    the same notify() call, never a different signal."""

    class FakeProc:
        def __init__(self, lines, returncode=0):
            self.stdout = iter(lines)
            self.returncode = returncode

        def wait(self):
            return self.returncode

    def _run_main(self, mod, tmp, lines, returncode=0):
        # A non-TTY stdin keeps main() on the plain path (no pty, no
        # forwarding thread): these tests are about notify() timing, not the
        # pty plumbing (covered by FeedbackGateFlowTest).
        with (
            mock.patch.object(Path, "cwd", return_value=Path(tmp)),
            mock.patch(
                "subprocess.Popen", return_value=self.FakeProc(lines, returncode)
            ),
            mock.patch.object(sys, "argv", ["run-pipeline.py", "adr-pipeline"]),
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stdin.isatty", return_value=False),
            mock.patch.object(mod, "notify") as notify,
        ):
            rc = mod.main()
        return rc, notify

    def test_gate_open_fires_notify(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify = self._run_main(
                mod, tmp, ["┌─ Gate ─────────", "Run ID: abc12345"], 0
            )
        self.assertEqual(rc, 0)
        self.assertEqual(notify.call_count, 2)  # gate open + successful finish

    def test_success_fires_notify(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify = self._run_main(mod, tmp, ["Run ID: abc12345"], 0)
        self.assertEqual(rc, 0)
        self.assertEqual(notify.call_count, 1)

    def test_failure_fires_notify(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify = self._run_main(mod, tmp, ["Run ID: abc12345"], 1)
        self.assertEqual(rc, 1)
        self.assertEqual(notify.call_count, 1)


class TruncateTest(unittest.TestCase):
    """Agent reasoning longer than MAX_LOG_TEXT_LEN is truncated for the
    console; the full text stays in the .jsonl (render only)."""

    def test_short_text_unchanged(self):
        mod = load_run_pipeline()
        self.assertEqual(mod.truncate(""), "")
        self.assertEqual(mod.truncate("short"), "short")

    def test_exactly_100_chars_unchanged(self):
        mod = load_run_pipeline()
        text = "x" * 100
        self.assertEqual(mod.truncate(text), text)

    def test_longer_than_100_chars_truncated_with_ellipsis(self):
        mod = load_run_pipeline()
        self.assertEqual(mod.truncate("x" * 101), "x" * 100 + "...")
        self.assertEqual(mod.truncate("x" * 250), "x" * 100 + "...")

    def test_render_log_event_truncates_long_text(self):
        mod = load_run_pipeline()
        line = json.dumps({"part": {"type": "text", "text": "y" * 150}})
        role, text = mod.render_log_event("planner", line)
        self.assertEqual((role, text), ("planner", "y" * 100 + "..."))


class LogAlignmentTest(unittest.TestCase):
    """Role labels are padded to the longest role name so the text after
    "[role] " starts at the same column for planner and executor."""

    def test_role_label_pads_to_longest_role(self):
        mod = load_run_pipeline()
        self.assertEqual(mod.role_label("planner"), "[planner ]")
        self.assertEqual(mod.role_label("executor"), "[executor]")

    def test_print_log_event_aligns_text_start(self):
        mod = load_run_pipeline()
        captured = io.StringIO()
        with (
            mock.patch("sys.stdout", captured),
            mock.patch.object(mod, "stamp", return_value="07:51:37"),
        ):
            mod.print_log_event("planner", "I verified")
            mod.print_log_event("executor", "SRP-review")
        lines = captured.getvalue().splitlines()
        self.assertTrue(lines[0].endswith("I verified"))
        self.assertTrue(lines[1].endswith("SRP-review"))
        # The text starts at the same column on both lines.
        self.assertEqual(
            lines[0].index("I verified"), lines[1].index("SRP-review")
        )
        self.assertTrue(lines[0].startswith("[07:51:37] [planner ] "))
        self.assertTrue(lines[1].startswith("[07:51:37] [executor] "))


class FeedbackGateRecognitionTest(unittest.TestCase):
    """The revise feedback gate is recognized by the "feedback-gate"
    substring of the step id (plain and loop-iteration forms)."""

    def test_recognizes_feedback_gate_ids(self):
        mod = load_run_pipeline()
        self.assertTrue(mod.is_feedback_gate("adr-feedback-gate"))
        self.assertTrue(mod.is_feedback_gate("adr-loop:adr-feedback-gate:1"))
        self.assertTrue(mod.is_feedback_gate("adr-loop:adr-feedback-gate:2"))

    def test_rejects_other_ids(self):
        mod = load_run_pipeline()
        self.assertFalse(mod.is_feedback_gate("adr-gate"))
        self.assertFalse(mod.is_feedback_gate("adr-approval-gate"))
        self.assertFalse(mod.is_feedback_gate("adr-loop:adr-gate:1"))
        self.assertFalse(mod.is_feedback_gate(""))
        self.assertFalse(mod.is_feedback_gate(None))


class FeedbackEditorResolutionTest(unittest.TestCase):
    """The feedback editor resolution chain: $VISUAL -> $EDITOR -> nano ->
    vi, each candidate validated on PATH; None when the whole chain is
    empty (unlike the launcher, which must always return something)."""

    def test_prefers_visual_over_editor(self):
        mod = load_run_pipeline()
        with (
            mock.patch.dict(
                "os.environ", {"VISUAL": "code --wait", "EDITOR": "vim"}, clear=True
            ),
            mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/" + name),
        ):
            self.assertEqual(mod.resolve_editor(), ["code", "--wait"])

    def test_uses_editor_when_visual_unset(self):
        mod = load_run_pipeline()
        with (
            mock.patch.dict("os.environ", {"EDITOR": "emacs -nw"}, clear=True),
            mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/" + name),
        ):
            self.assertEqual(mod.resolve_editor(), ["emacs", "-nw"])

    def test_missing_binary_falls_through_to_next_candidate(self):
        # A VISUAL/EDITOR whose binary is not on PATH is skipped and the
        # chain continues (the launcher would return it as-is instead).
        mod = load_run_pipeline()

        def which(name):
            return "/usr/bin/" + name if name == "vim" else None

        with (
            mock.patch.dict(
                "os.environ", {"VISUAL": "subl", "EDITOR": "vim"}, clear=True
            ),
            mock.patch("shutil.which", side_effect=which),
        ):
            self.assertEqual(mod.resolve_editor(), ["vim"])

    def test_malformed_visual_is_skipped_with_warning(self):
        mod = load_run_pipeline()
        with (
            mock.patch.dict(
                "os.environ", {"VISUAL": 'code --wait"', "EDITOR": "vim"}, clear=True
            ),
            mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/" + name),
            mock.patch("sys.stderr", io.StringIO()) as stderr,
        ):
            self.assertEqual(mod.resolve_editor(), ["vim"])
        self.assertIn("warning", stderr.getvalue())

    def test_falls_back_to_nano_then_vi(self):
        mod = load_run_pipeline()

        def with_nano(name):
            return "/usr/bin/" + name if name in ("nano", "vi") else None

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", side_effect=with_nano),
        ):
            self.assertEqual(mod.resolve_editor(), ["nano"])

        def vi_only(name):
            return "/usr/bin/vi" if name == "vi" else None

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", side_effect=vi_only),
        ):
            self.assertEqual(mod.resolve_editor(), ["vi"])

    def test_no_editor_available_returns_none(self):
        mod = load_run_pipeline()
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value=None),
        ):
            self.assertIsNone(mod.resolve_editor())


class FeedbackFileTest(unittest.TestCase):
    """feedback.md is created empty when missing and never overwritten."""

    def test_creates_empty_file_with_parents(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks" / "current" / "feedback.md"
            mod.create_feedback_file(path)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_never_overwrites_existing_feedback(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            path.write_text("keep me", encoding="utf-8")
            mod.create_feedback_file(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "keep me")


class FeedbackEditorTest(unittest.TestCase):
    """open_feedback_editor owns the revise gate: on a TTY with a usable
    editor it runs the editor and answers `continue`; otherwise it falls
    back (file created, gate stays interactive, forwarding never paused)."""

    @contextmanager
    def _tty(self, is_tty=True):
        with (
            mock.patch("sys.stdin.isatty", return_value=is_tty),
            mock.patch("sys.stdout.isatty", return_value=is_tty),
        ):
            yield

    def test_answers_continue_after_editor(self):
        mod = load_run_pipeline()
        real_master, real_slave = pty.openpty()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "feedback.md"
                written = []
                with (
                    self._tty(),
                    mock.patch.dict("os.environ", {}, clear=True),
                    mock.patch("shutil.which", return_value="/usr/bin/nano"),
                    mock.patch(
                        "subprocess.run", return_value=mock.Mock(returncode=0)
                    ) as run,
                    mock.patch(
                        "os.write",
                        side_effect=lambda fd, data: written.append((fd, data))
                        or len(data),
                    ),
                ):
                    result = mod.open_feedback_editor(
                        path, threading.Event(), real_master
                    )
                self.assertTrue(result)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0], ["nano", str(path)])
                self.assertEqual(written, [(real_master, b"continue\n")])
        finally:
            os.close(real_master)
            os.close(real_slave)

    def test_falls_back_when_not_a_tty(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            with (
                self._tty(is_tty=False),
                mock.patch("subprocess.run") as run,
                mock.patch("os.write") as write,
            ):
                result = mod.open_feedback_editor(path, threading.Event(), 999)
            self.assertFalse(result)
            run.assert_not_called()
            write.assert_not_called()
            # The file is still created (the fallback keeps manual input).
            self.assertTrue(path.is_file())

    def test_falls_back_when_no_editor(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            with (
                self._tty(),
                mock.patch("shutil.which", return_value=None),
                mock.patch("subprocess.run") as run,
            ):
                result = mod.open_feedback_editor(path, threading.Event(), 999)
            self.assertFalse(result)
            run.assert_not_called()
            self.assertTrue(path.is_file())

    def test_fallback_never_leaves_forwarding_paused(self):
        # In the fallback the user answers the gate manually, so stdin
        # forwarding must never be left paused.
        mod = load_run_pipeline()
        pause = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            with self._tty(is_tty=False):
                result = mod.open_feedback_editor(path, pause, 999)
            self.assertFalse(result)
            self.assertFalse(pause.is_set())

    def test_editor_failure_falls_back(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            with (
                self._tty(),
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch("shutil.which", return_value="/usr/bin/nano"),
                mock.patch("subprocess.run", side_effect=OSError("boom")),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                result = mod.open_feedback_editor(path, threading.Event(), 999)
            self.assertFalse(result)


class ForwardInputTest(unittest.TestCase):
    """forward_terminal_input copies terminal lines into the pty master and
    pauses while the feedback editor is open."""

    def _setup(self):
        read_fd, write_fd = os.pipe()
        master_fd, slave_fd = pty.openpty()
        # The text-mode file owns read_fd: it is closed via source.close()
        # (a GC of the file object closes the fd first, so os.close would
        # raise EBADF).
        source = os.fdopen(read_fd, "r")
        return source, write_fd, master_fd, slave_fd

    def _read_echo(self, master_fd, expected_bytes, timeout=2.0):
        # The pty line discipline echoes with \n translated to \r\n (ONLCR);
        # strip \r before comparing.
        deadline = time.monotonic() + timeout
        data = b""
        while time.monotonic() < deadline and len(data) < len(expected_bytes):
            try:
                data += os.read(master_fd, 16)
            except BlockingIOError:
                time.sleep(0.05)
        return data.replace(b"\r", b"")

    def test_forwards_terminal_lines_into_pty(self):
        mod = load_run_pipeline()
        source, write_fd, master_fd, slave_fd = self._setup()
        try:
            stop = threading.Event()
            thread = threading.Thread(
                target=mod.forward_terminal_input,
                args=(source, master_fd, threading.Event(), stop),
                daemon=True,
            )
            thread.start()
            os.write(write_fd, b"2\n")
            # The pty line discipline echoes the forwarded line back: reading
            # the master proves the wrapper forwarded it into specify's stdin.
            self.assertEqual(self._read_echo(master_fd, b"2\n"), b"2\n")
            stop.set()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
        finally:
            source.close()
            os.close(write_fd)
            os.close(master_fd)
            os.close(slave_fd)

    def test_paused_while_editor_open(self):
        mod = load_run_pipeline()
        source, write_fd, master_fd, slave_fd = self._setup()
        try:
            pause = threading.Event()
            pause.set()
            stop = threading.Event()
            thread = threading.Thread(
                target=mod.forward_terminal_input,
                args=(source, master_fd, pause, stop),
                daemon=True,
            )
            thread.start()
            os.write(write_fd, b"2\n")
            os.set_blocking(master_fd, False)
            with self.assertRaises(BlockingIOError):
                os.read(master_fd, 16)
            pause.clear()
            # After the editor closes the pending line is forwarded.
            self.assertEqual(self._read_echo(master_fd, b"2\n"), b"2\n")
            stop.set()
            thread.join(timeout=1)
        finally:
            os.set_blocking(master_fd, True)
            source.close()
            os.close(write_fd)
            os.close(master_fd)
            os.close(slave_fd)


class LiveMonitorLogOrderTest(unittest.TestCase):
    """Agent log lines print BEFORE the step's "--- step X (completed)"
    marker."""

    def test_logs_print_before_step_marker(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            run_dir = state / "workflows" / "runs" / "abc12345"
            run_dir.mkdir(parents=True)
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
            logs_dir = state / ".workflow" / "logs"
            logs_dir.mkdir(parents=True)
            log = logs_dir / "sessions-executor.jsonl"
            with mock.patch.object(Path, "cwd", return_value=state):
                monitor = mod.LiveMonitor(state, set())
                monitor.run_id = "abc12345"
                # The agent line is appended after the tailer's baseline,
                # like a line written by the finishing step.
                log.write_text(
                    '{"part": {"type": "text", "text": "final agent line"}}\n',
                    encoding="utf-8",
                )
                captured = io.StringIO()
                with mock.patch("sys.stdout", captured):
                    monitor._poll_once()
            out = captured.getvalue()
            self.assertLess(
                out.index("final agent line"),
                out.index("--- step write-adr (completed)"),
            )


class FeedbackGateFlowTest(unittest.TestCase):
    """main() recognizes the ADR revise feedback gate: the editor opens and
    no victory sound is played (both for the editor path and the manual
    fallback); regular gates still notify()."""

    class FakeProc:
        def __init__(self, lines, returncode=0):
            self.stdout = iter(lines)
            self.returncode = returncode

        def wait(self):
            return self.returncode

    def _run_main(self, mod, tmp, step_id, editor_result):
        state_root = Path(tmp) / ".specify"
        run_dir = state_root / "workflows" / "runs" / "abc12345"
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text(
            json.dumps({"current_step_id": step_id}), encoding="utf-8"
        )
        real_master, real_slave = pty.openpty()
        # The run dir exists before main() starts; the wrapper snapshots
        # prior runs BEFORE the workflow starts, so the first existing_run_ids
        # call must see nothing (making abc12345 look like it appeared during
        # the run) and later calls must find it.
        state = {"calls": 0}

        def fake_existing(state_dir):
            state["calls"] += 1
            return {"abc12345"} if state["calls"] > 1 else set()

        try:
            with (
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("sys.stdin", mock.Mock(isatty=lambda: True)),
                mock.patch("pty.openpty", return_value=(real_master, real_slave)),
                mock.patch(
                    "subprocess.Popen",
                    return_value=self.FakeProc(
                        ["┌─ Gate ─────────", "Run ID: abc12345"], 0
                    ),
                ),
                mock.patch.object(sys, "argv", ["run-pipeline.py", "adr-pipeline"]),
                mock.patch("sys.stdout", io.StringIO()),
                mock.patch.object(mod, "notify") as notify,
                mock.patch.object(
                    mod, "open_feedback_editor", return_value=editor_result
                ) as editor,
                mock.patch.object(mod, "forward_terminal_input"),
                mock.patch.object(
                    mod, "existing_run_ids", side_effect=fake_existing
                ),
            ):
                rc = mod.main()
        finally:
            for fd in (real_master, real_slave):
                with contextlib.suppress(OSError):
                    os.close(fd)
        return rc, notify, editor

    def test_feedback_gate_opens_editor_without_sound(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify, editor = self._run_main(
                mod, tmp, "adr-feedback-gate", editor_result=True
            )
        self.assertEqual(rc, 0)
        editor.assert_called_once()
        feedback_path = editor.call_args.args[0]
        self.assertTrue(str(feedback_path).endswith("tasks/current/feedback.md"))
        # No victory sound for the feedback gate itself: only the final
        # success signal fires.
        self.assertEqual(notify.call_count, 1)

    def test_feedback_gate_loop_iteration_without_sound(self):
        # The loop-iteration form of the feedback gate id is recognized too.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify, editor = self._run_main(
                mod, tmp, "adr-loop:adr-feedback-gate:1", editor_result=True
            )
        self.assertEqual(rc, 0)
        editor.assert_called_once()
        self.assertEqual(notify.call_count, 1)

    def test_feedback_gate_fallback_without_sound(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify, editor = self._run_main(
                mod, tmp, "adr-feedback-gate", editor_result=False
            )
        self.assertEqual(rc, 0)
        editor.assert_called_once()
        self.assertEqual(notify.call_count, 1)

    def test_regular_gate_still_notifies(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify, editor = self._run_main(
                mod, tmp, "adr-gate", editor_result=True
            )
        self.assertEqual(rc, 0)
        editor.assert_not_called()
        # gate open + successful finish
        self.assertEqual(notify.call_count, 2)


if __name__ == "__main__":
    unittest.main()
