"""Unit tests for feedback.md creation."""

import tempfile
import unittest
from pathlib import Path

from .helpers import load_run_pipeline


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
