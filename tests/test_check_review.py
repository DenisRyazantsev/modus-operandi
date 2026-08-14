"""Unit tests for templates/check_review.py (review-loop verdict gate)."""

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# check_review.py imports task_utils.py from the same directory.
sys.path.insert(0, str(REPO_ROOT / "templates"))

_SPEC = importlib.util.spec_from_file_location(
    "check_review", REPO_ROOT / "templates" / "check_review.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_review = importlib.util.module_from_spec(_SPEC)
sys.modules["check_review"] = check_review
_SPEC.loader.exec_module(check_review)


class CmdCheckReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)

    def check(self, kind):
        return check_review.cmd_check_review(
            argparse.Namespace(
                state_dir=str(self.root / ".workflow"), task_id="t1", kind=kind
            )
        )

    def test_pass_exits_zero(self):
        (self.task_dir / "review-1.md").write_text(
            "VERDICT: PASS\n- fine\n", encoding="utf-8"
        )
        (self.task_dir / "review-2.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("review")
        self.assertEqual(cm.exception.code, 0)

    def test_fix_exits_one(self):
        (self.task_dir / "review-1.md").write_text(
            "VERDICT: FIX\n- x\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("review")
        self.assertEqual(cm.exception.code, 1)

    def test_no_files_exits_one(self):
        with self.assertRaises(SystemExit) as cm:
            self.check("review")
        self.assertEqual(cm.exception.code, 1)

    def test_latest_file_wins(self):
        (self.task_dir / "review-1.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        (self.task_dir / "review-2.md").write_text(
            "VERDICT: FIX\n- x\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("review")
        self.assertEqual(cm.exception.code, 1)

    def test_srp_kind_uses_srp_marker(self):
        (self.task_dir / "srp-review-1.md").write_text(
            "SRP: FIX\n- x\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("srp")
        self.assertEqual(cm.exception.code, 1)
        (self.task_dir / "srp-review-2.md").write_text(
            "SRP: PASS\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("srp")
        self.assertEqual(cm.exception.code, 0)

    def test_bugs_kind_uses_bug_marker(self):
        (self.task_dir / "bug-review-1.md").write_text(
            "BUGS: FIX\n- x\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("bugs")
        self.assertEqual(cm.exception.code, 1)
        (self.task_dir / "bug-review-2.md").write_text(
            "BUGS: PASS\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("bugs")
        self.assertEqual(cm.exception.code, 0)

    def test_comment_kind_uses_comment_review_files_and_verdict_marker(self):
        (self.task_dir / "comment-review-1.md").write_text(
            "VERDICT: FIX\n- x\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("comment")
        self.assertEqual(cm.exception.code, 1)
        (self.task_dir / "comment-review-2.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("comment")
        self.assertEqual(cm.exception.code, 0)

    def test_comment_kind_ignores_plain_review_files(self):
        (self.task_dir / "review-1.md").write_text(
            "VERDICT: FIX\n- x\n", encoding="utf-8"
        )
        (self.task_dir / "comment-review-1.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("comment")
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
