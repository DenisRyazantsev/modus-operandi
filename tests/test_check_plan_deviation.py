"""Unit tests for pipeline_scripts/check_plan_deviation.py (plan-deviation-loop exit gate)."""

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
# check_plan_deviation.py imports task_utils.py from the same directory.
sys.path.insert(0, str(REPO_ROOT / "src/modus_operandi/data/pipeline_scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "check_plan_deviation",
    REPO_ROOT / "src/modus_operandi/data/pipeline_scripts" / "check_plan_deviation.py",
)
assert _SPEC is not None and _SPEC.loader is not None
check_plan_deviation = importlib.util.module_from_spec(_SPEC)
sys.modules["check_plan_deviation"] = check_plan_deviation
_SPEC.loader.exec_module(check_plan_deviation)


class CmdCheckPlanDeviationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)

    def check(self) -> Any:
        return check_plan_deviation.cmd_check(
            argparse.Namespace(state_dir=str(self.root / ".workflow"), task_id="t1")
        )

    def test_no_deviation_file_exits_zero(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 0)

    def test_deviation_file_exits_one(self) -> None:
        (self.task_dir / "plan-deviation.md").write_text(
            "cannot follow the plan\n", encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 1)

    def test_deleted_after_agreement_exits_zero(self) -> None:
        # The planner-agreement step deletes plan-deviation.md after
        # resolving it, so the loop's next iteration sees the file gone and
        # exits.
        (self.task_dir / "plan-deviation.md").write_text("x\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 1)
        (self.task_dir / "plan-deviation.md").unlink()
        with self.assertRaises(SystemExit) as cm:
            self.check()
        self.assertEqual(cm.exception.code, 0)

    def test_empty_task_id_resolves_through_current_symlink(self) -> None:
        # The workflow passes the generated task id; when it is empty the
        # script resolves it through the tasks/current symlink.
        current = self.root / ".workflow" / "tasks" / "current"
        current.symlink_to(self.task_dir)
        (self.task_dir / "plan-deviation.md").write_text("x\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            check_plan_deviation.cmd_check(
                argparse.Namespace(state_dir=str(self.root / ".workflow"), task_id="")
            )
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
