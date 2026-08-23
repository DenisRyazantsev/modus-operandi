"""Unit tests for the AgentLogTailer class."""

import tempfile
import unittest
from pathlib import Path

from .helpers import load_run_pipeline


class AgentLogTailerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_run_pipeline()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_unterminated_tail_is_held_back_for_next_poll(self) -> None:
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
        log.write_text(complete + '{"part": {"type": "text", "text": "work"}}\n', encoding="utf-8")
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, ['{"part": {"type": "text", "text": "work"}}'])
        self.assertEqual(pos, log.stat().st_size)

    def test_wholly_unterminated_chunk_reads_nothing(self) -> None:
        log = self.dir / "x-executor.jsonl"
        tailer = self.mod.AgentLogTailer(self.dir)
        log.write_text('{"part": {"type": "text", "text": "abc', encoding="utf-8")
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, [])
        self.assertEqual(pos, 0)

    def test_multibyte_lines_keep_byte_offsets(self) -> None:
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

    def test_unterminated_multibyte_tail_held_back_in_bytes(self) -> None:
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

    def test_read_error_does_not_skip_chunk(self) -> None:
        log = self.dir / "x-executor.jsonl"
        tailer = self.mod.AgentLogTailer(self.dir)
        log.write_text("first line\n", encoding="utf-8")
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, ["first line"])
        log.write_text("first line\nsecond line\n", encoding="utf-8")
        # A transient read failure (the path replaced by a directory: open
        # raises IsADirectoryError) must not advance the recorded position.
        log.unlink()
        log.mkdir()
        try:
            lines, pos = tailer._read_appended(log)
        finally:
            log.rmdir()
        self.assertEqual(lines, [])
        self.assertEqual(pos, len("first line\n"))
        # The chunk is retried on the next poll, not permanently skipped.
        log.write_text("first line\nsecond line\n", encoding="utf-8")
        lines, pos = tailer._read_appended(log)
        self.assertEqual(lines, ["second line"])

    def test_preexisting_log_content_is_skipped(self) -> None:
        # Files that existed before the wrapper started were written by
        # previous runs (the logs dir is never cleaned): the tailer baselines
        # their sizes at construction, so only lines appended during the
        # current run are yielded.
        log = self.dir / "sessions-executor.jsonl"
        old = '{"part": {"type": "text", "text": "old"}}\n'
        log.write_text(old, encoding="utf-8")
        tailer = self.mod.AgentLogTailer(self.dir)
        self.assertEqual(tailer.tail(), [])
        # The current run appends a line: only that line is yielded, with
        # the parsed event and an empty rendered text (ADR-0011).
        log.write_text(old + '{"part": {"type": "text", "text": "new"}}\n', encoding="utf-8")
        events = tailer.tail()
        self.assertEqual(len(events), 1)
        role, fork_id, text, event = events[0]
        self.assertEqual(role, "executor")
        self.assertEqual(fork_id, "")
        self.assertEqual(text, "")
        self.assertEqual(event["part"]["text"], "new")

    def test_new_file_after_baseline_starts_from_zero(self) -> None:
        # A log file created after the baseline (by the current run) is not
        # in the snapshot and starts at offset 0.
        tailer = self.mod.AgentLogTailer(self.dir)
        log = self.dir / "sessions-planner.jsonl"
        log.write_text('{"part": {"type": "text", "text": "fresh"}}\n', encoding="utf-8")
        events = tailer.tail()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "planner")
        self.assertEqual(events[0][1], "")

    def test_fork_log_files_carry_role_and_fork_id(self) -> None:
        # The review kinds write stable per-kind logs
        # (sessions-<task>-<role>-fork-<kind>.jsonl, ADR-0013): the
        # -fork-<kind> suffix must not leak into the role label, and the
        # fork id (the kind) must be carried for the live status lines'
        # separate accumulators labeled [planner#<kind>].
        tailer = self.mod.AgentLogTailer(self.dir)
        log = self.dir / "sessions-parallel-review-20260816-planner-fork-srp.jsonl"
        log.write_text(
            '{"type": "step_finish", "part": {"tokens": {"input": 1}}}\n',
            encoding="utf-8",
        )
        events = tailer.tail()
        self.assertEqual(len(events), 1)
        role, fork_id, text, event = events[0]
        self.assertEqual(role, "planner")
        self.assertEqual(fork_id, "srp")
        self.assertEqual(text, "")
        self.assertEqual(event["type"], "step_finish")

    def test_reviewer_role_logs_label_by_role(self) -> None:
        # ADR-0017: the reviewers run under their own roles, and their logs
        # are named after the role (sessions-<task>-reviewer-srp.jsonl): the
        # role label is the last segment, with no fork id — the live status
        # lines show [reviewer-srp].
        tailer = self.mod.AgentLogTailer(self.dir)
        log = self.dir / "sessions-task-42-reviewer-srp.jsonl"
        log.write_text(
            '{"type": "step_finish", "part": {"tokens": {"input": 1}}}\n',
            encoding="utf-8",
        )
        events = tailer.tail()
        self.assertEqual(len(events), 1)
        role, fork_id, text, event = events[0]
        self.assertEqual(role, "reviewer-srp")
        self.assertEqual(fork_id, "")
        self.assertEqual(event["type"], "step_finish")

    def test_fork_log_files_accept_kinds_with_digits_and_dashes(self) -> None:
        # The per-kind regex is ^[A-Za-z0-9_-]+$: a task-id-scoped kind
        # suffix (e.g. a future loop id) must still parse.
        tailer = self.mod.AgentLogTailer(self.dir)
        log = self.dir / "sessions-task-42-planner-fork-bugs-2.jsonl"
        log.write_text('{"type": "step_finish", "part": {}}\n', encoding="utf-8")
        events = tailer.tail()
        self.assertEqual(len(events), 1)
        role, fork_id, text, event = events[0]
        self.assertEqual(role, "planner")
        self.assertEqual(fork_id, "bugs-2")

    def test_task_id_containing_fork_does_not_misattribute_role(self) -> None:
        # Regression (bug fix): the fork marker is anchored to the role
        # ("-<role>-fork-<kind>"), not a bare "-fork-" — a task id that
        # itself contains "-fork-" (branch-derived slugs like
        # feature-fork-x) must not turn a warm log into a phantom fork with
        # a garbage fork id and role.
        tailer = self.mod.AgentLogTailer(self.dir)
        # The warm planner log of a task whose slug contains "fork".
        warm = self.dir / "sessions-feature-fork-x-20260822-0900-planner.jsonl"
        warm.write_text('{"type": "step_finish", "part": {}}\n', encoding="utf-8")
        # The real per-kind fork log of the same task.
        fork = self.dir / "sessions-feature-fork-x-20260822-0900-planner-fork-srp.jsonl"
        fork.write_text('{"type": "step_finish", "part": {}}\n', encoding="utf-8")
        events = tailer.tail()
        self.assertEqual(len(events), 2)
        # The fork log parses first (lexicographic file order): its fork id
        # is the real kind, not the slug fragments.
        role, fork_id, text, event = events[0]
        self.assertEqual(role, "planner")
        self.assertEqual(fork_id, "srp")
        # The warm log keeps its real role and no phantom fork id.
        role, fork_id, text, event = events[1]
        self.assertEqual(role, "planner")
        self.assertEqual(fork_id, "")

    def test_non_json_line_yields_none_event(self) -> None:
        # A non-JSON line still yields a quadruple (the raw text is
        # suppressed since ADR-0011) with event=None.
        tailer = self.mod.AgentLogTailer(self.dir)
        log = self.dir / "sessions-executor.jsonl"
        log.write_text("plain line\n", encoding="utf-8")
        events = tailer.tail()
        self.assertEqual(len(events), 1)
        role, fork_id, text, event = events[0]
        self.assertEqual(role, "executor")
        self.assertEqual(text, "")
        self.assertIsNone(event)
