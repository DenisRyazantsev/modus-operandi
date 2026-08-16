"""Unit tests for pipeline_scripts/check_review.py (review-loop verdict gate)."""

import argparse
import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# check_review.py imports task_utils.py from the same directory.
sys.path.insert(0, str(REPO_ROOT / "pipeline_scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "check_review", REPO_ROOT / "pipeline_scripts" / "check_review.py"
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

    def test_numeric_sort_picks_10_over_9(self):
        # Lexicographic order would pick review-9.md as "latest"; the
        # version-order sort must pick review-10.md.
        (self.task_dir / "review-2.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        (self.task_dir / "review-9.md").write_text(
            "VERDICT: FIX\n- x\n", encoding="utf-8"
        )
        (self.task_dir / "review-10.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("review")
        self.assertEqual(cm.exception.code, 0)

    def test_empty_latest_file_exits_one(self):
        (self.task_dir / "review-1.md").write_text("", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.check("review")
        self.assertEqual(cm.exception.code, 1)

    def test_stray_file_without_number_is_ignored(self):
        # review-notes.md matches the glob but has no numeric suffix; the
        # gate must ignore it (not crash on the missing suffix).
        (self.task_dir / "review-notes.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        (self.task_dir / "review-2.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check("review")
        self.assertEqual(cm.exception.code, 0)

    def test_only_stray_files_exit_one(self):
        (self.task_dir / "review-notes.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
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

    # -- pending (ADR-0009: kinds the parallel fan-out must re-run) ----------

    def pending(self):
        return check_review.cmd_pending(
            argparse.Namespace(
                state_dir=str(self.root / ".workflow"), task_id="t1"
            )
        )

    def merge(self):
        return check_review.cmd_merge(
            argparse.Namespace(
                state_dir=str(self.root / ".workflow"), task_id="t1"
            )
        )

    def pending_stdout(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(buf):
            self.pending()
        self.assertEqual(cm.exception.code, 0)
        return buf.getvalue()

    def test_pending_all_kinds_when_no_reports(self):
        self.assertEqual(
            self.pending_stdout(),
            '["srp", "bugs", "review", "comment"]\n',
        )

    def test_pending_only_failed_kinds(self):
        (self.task_dir / "srp-review-1.md").write_text("SRP: PASS\n", encoding="utf-8")
        (self.task_dir / "bug-review-1.md").write_text("BUGS: FIX\n- x\n", encoding="utf-8")
        (self.task_dir / "review-1.md").write_text("VERDICT: PASS\n", encoding="utf-8")
        (self.task_dir / "comment-review-1.md").write_text("VERDICT: FIX\n- y\n", encoding="utf-8")
        self.assertEqual(self.pending_stdout(), '["bugs", "comment"]\n')

    def test_pending_none_when_all_pass(self):
        for name, marker in (
            ("srp-review-1.md", "SRP: PASS"),
            ("bug-review-1.md", "BUGS: PASS"),
            ("review-1.md", "VERDICT: PASS"),
            ("comment-review-1.md", "VERDICT: PASS"),
        ):
            (self.task_dir / name).write_text(marker + "\n", encoding="utf-8")
        self.assertEqual(self.pending_stdout(), "[]\n")

    # -- merge (ADR-0009: deterministic review-report.md for the executor) ---

    def test_merge_concatenates_all_four_sections(self):
        (self.task_dir / "srp-review-1.md").write_text(
            "SRP: FIX\n- split file.py\n", encoding="utf-8"
        )
        (self.task_dir / "bug-review-1.md").write_text(
            "BUGS: PASS\n", encoding="utf-8"
        )
        (self.task_dir / "review-1.md").write_text(
            "VERDICT: FIX\n- handle the edge case\n", encoding="utf-8"
        )
        (self.task_dir / "comment-review-1.md").write_text(
            "VERDICT: PASS\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.merge()
        self.assertEqual(cm.exception.code, 1)  # review/srp still FIX
        report = (self.task_dir / "review-report.md").read_text(encoding="utf-8")
        self.assertIn("## SRP review", report)
        self.assertIn("## Bugs review", report)
        self.assertIn("## General review", report)
        self.assertIn("## Comment (readability) review", report)
        # Sections are concatenated with headings, no synthesis: the FIX
        # bodies survive verbatim.
        self.assertIn("split file.py", report)
        self.assertIn("handle the edge case", report)

    def test_merge_exits_zero_only_when_all_pass(self):
        for name, marker in (
            ("srp-review-1.md", "SRP: PASS"),
            ("bug-review-1.md", "BUGS: PASS"),
            ("review-1.md", "VERDICT: PASS"),
            ("comment-review-1.md", "VERDICT: PASS"),
        ):
            (self.task_dir / name).write_text(marker + "\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.merge()
        self.assertEqual(cm.exception.code, 0)
        report = (self.task_dir / "review-report.md").read_text(encoding="utf-8")
        for heading in (
            "## SRP review",
            "## Bugs review",
            "## General review",
            "## Comment (readability) review",
        ):
            self.assertIn(heading, report)

    def test_merge_uses_latest_report_per_kind(self):
        (self.task_dir / "review-1.md").write_text("VERDICT: FIX\n- old\n", encoding="utf-8")
        (self.task_dir / "review-2.md").write_text("VERDICT: PASS\n", encoding="utf-8")
        (self.task_dir / "srp-review-1.md").write_text("SRP: PASS\n", encoding="utf-8")
        (self.task_dir / "bug-review-1.md").write_text("BUGS: PASS\n", encoding="utf-8")
        (self.task_dir / "comment-review-1.md").write_text("VERDICT: PASS\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.merge()
        self.assertEqual(cm.exception.code, 0)
        report = (self.task_dir / "review-report.md").read_text(encoding="utf-8")
        self.assertNotIn("old", report)
        self.assertIn("VERDICT: PASS", report)


if __name__ == "__main__":
    unittest.main()
