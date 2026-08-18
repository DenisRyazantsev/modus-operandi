"""Unit tests for pipeline_scripts/check_questions.py (questions-loop exit gate)."""

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# check_questions.py imports task_utils.py from the same directory.
sys.path.insert(0, str(REPO_ROOT / "pipeline_scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "check_questions", REPO_ROOT / "pipeline_scripts" / "check_questions.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_questions = importlib.util.module_from_spec(_SPEC)
sys.modules["check_questions"] = check_questions
_SPEC.loader.exec_module(check_questions)


class CmdCheckQuestionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)

    def check(self):
        return check_questions.cmd_check(
            argparse.Namespace(
                state_dir=str(self.root / ".workflow"), task_id="t1"
            )
        )

    def test_none_first_line_exits_zero(self):
        (self.task_dir / "questions.md").write_text(
            "QUESTIONS: NONE\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 0)

    def test_present_first_line_exits_one(self):
        (self.task_dir / "questions.md").write_text(
            "QUESTIONS: PRESENT\n1. what?\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 1)

    def test_missing_file_exits_one(self):
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 1)

    def test_empty_file_exits_one(self):
        (self.task_dir / "questions.md").write_text("", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 1)

    def test_leading_whitespace_on_marker_is_tolerated(self):
        (self.task_dir / "questions.md").write_text(
            "  QUESTIONS: NONE\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 0)

    def test_marker_not_on_first_line_exits_one(self):
        (self.task_dir / "questions.md").write_text(
            "1. what?\nQUESTIONS: NONE\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 1)

    def test_empty_task_id_resolves_through_current_symlink(self):
        # The workflow passes the generated task id; when it is empty the
        # script resolves it through the tasks/current symlink.
        current = self.root / ".workflow" / "tasks" / "current"
        current.symlink_to(self.task_dir)
        (self.task_dir / "questions.md").write_text(
            "QUESTIONS: NONE\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            check_questions.cmd_check(
                argparse.Namespace(
                    state_dir=str(self.root / ".workflow"), task_id=""
                )
            )
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
