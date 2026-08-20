"""Unit tests for the launcher's installed-path derivation."""

import tempfile
import unittest
from pathlib import Path

from .helpers import load_spec_run


class LauncherPathsTest(unittest.TestCase):
    def test_paths_derived_from_config_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = load_spec_run(tmp)
            base = Path(tmp)
            self.assertEqual(
                mod.RUN_PIPELINE, str(base / "opencode" / "scripts" / "run-pipeline.py")
            )
            self.assertEqual(
                mod.REVIEW_WORKFLOW,
                str(base / "spec-run" / "review-pipeline.yml"),
            )
            self.assertEqual(
                mod.TASK_WORKFLOW,
                str(base / "spec-run" / "task-pipeline.yml"),
            )
            self.assertEqual(
                mod.CONFIG, str(base / "spec-run" / "config.yml")
            )
