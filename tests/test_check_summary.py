"""Unit tests for pipeline_scripts/check_summary.py (summary warning guard, ADR-0019)."""

import argparse
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
# check_summary.py imports task_utils.py from the same directory.
sys.path.insert(0, str(REPO_ROOT / "src/modus_operandi/data/pipeline_scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "check_summary", REPO_ROOT / "src/modus_operandi/data/pipeline_scripts" / "check_summary.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_summary = importlib.util.module_from_spec(_SPEC)
sys.modules["check_summary"] = check_summary
_SPEC.loader.exec_module(check_summary)


class CmdCheckSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)

    def check(self) -> Any:
        return check_summary.cmd_check(
            argparse.Namespace(state_dir=str(self.root / ".workflow"), task_id="t1")
        )

    def test_summary_exists_exits_zero(self) -> None:
        (self.task_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 0)

    def test_missing_summary_exits_one_with_warning(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("summary.md", err.getvalue())

    def test_empty_task_id_resolves_through_current_symlink(self) -> None:
        # The review-pipeline passes an empty task id; the script resolves
        # it through the tasks/current symlink.
        current = self.root / ".workflow" / "tasks" / "current"
        current.symlink_to(self.task_dir)
        (self.task_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            check_summary.cmd_check(
                argparse.Namespace(state_dir=str(self.root / ".workflow"), task_id="")
            )
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
