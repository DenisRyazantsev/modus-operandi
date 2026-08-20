"""Unit tests for pipeline_scripts/task_utils.py (shared task-dir resolution)."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src/spec_run/data/pipeline_scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "task_utils", REPO_ROOT / "src/spec_run/data/pipeline_scripts" / "task_utils.py"
)
assert _SPEC is not None and _SPEC.loader is not None
task_utils = importlib.util.module_from_spec(_SPEC)
sys.modules["task_utils"] = task_utils
_SPEC.loader.exec_module(task_utils)


class ResolveTaskDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tasks = self.root / ".workflow" / "tasks"
        self.tasks.mkdir(parents=True)

    def test_explicit_task_id(self):
        task_dir = task_utils.resolve_task_dir(str(self.root / ".workflow"), "t1")
        self.assertEqual(task_dir, self.tasks / "t1")

    def test_empty_task_id_resolves_symlink(self):
        (self.tasks / "mcc-split-20260814").mkdir()
        (self.tasks / "current").symlink_to("mcc-split-20260814")
        task_dir = task_utils.resolve_task_dir(str(self.root / ".workflow"), "")
        self.assertEqual(task_dir, self.tasks / "mcc-split-20260814")
        self.assertEqual(task_dir.name, "mcc-split-20260814")

    def test_empty_task_id_without_symlink_fails(self):
        with self.assertRaises(SystemExit):
            task_utils.resolve_task_dir(str(self.root / ".workflow"), "")

    def test_empty_task_id_broken_symlink_fails(self):
        (self.tasks / "current").symlink_to("missing-task")
        with self.assertRaises(SystemExit):
            task_utils.resolve_task_dir(str(self.root / ".workflow"), "")

    def test_empty_task_id_with_real_dir_fails(self):
        # `tasks/current` being a real directory rather than a symlink is an
        # invalid install: resolve_task_dir must reject it (guard compares
        # against the resolved path) instead of silently returning it.
        (self.tasks / "current").mkdir()
        with self.assertRaises(SystemExit):
            task_utils.resolve_task_dir(str(self.root / ".workflow"), "")


if __name__ == "__main__":
    unittest.main()
