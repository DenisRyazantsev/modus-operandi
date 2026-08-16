"""Unit tests for the AgentLogTailer class."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


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

    def test_fork_log_files_still_derive_the_role(self):
        # Parallel review forks write per-invocation logs
        # (sessions-<task>-<role>-fork-<pid>.jsonl, ADR-0009): the -fork-<pid>
        # suffix must not leak into the role label.
        tailer = self.mod.AgentLogTailer(self.dir)
        log = self.dir / "sessions-parallel-review-20260816-planner-fork-4242.jsonl"
        log.write_text(
            '{"part": {"type": "text", "text": "fork line"}}\n', encoding="utf-8"
        )
        self.assertEqual(tailer.tail(), [("planner", "fork line")])
