"""Unit tests for console truncation of long agent-log text."""

import json
import unittest

from .helpers import load_run_pipeline


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
