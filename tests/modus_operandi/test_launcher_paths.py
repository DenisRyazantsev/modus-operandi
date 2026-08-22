"""Unit tests for the launcher's installed-path derivation."""

import tempfile
import unittest
from pathlib import Path

from .helpers import load_modus_operandi


class LauncherPathsTest(unittest.TestCase):
    def test_paths_derived_from_config_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = load_modus_operandi(tmp)
            base = Path(tmp)
            self.assertEqual(
                mod.RUN_PIPELINE, str(base / "opencode" / "scripts" / "run-pipeline.py")
            )
            self.assertEqual(
                mod.REVIEW_WORKFLOW,
                str(base / "modus-operandi" / "review-pipeline.yml"),
            )
            self.assertEqual(
                mod.TASK_WORKFLOW,
                str(base / "modus-operandi" / "task-pipeline.yml"),
            )
            self.assertEqual(mod.CONFIG, str(base / "modus-operandi" / "config.yml"))
