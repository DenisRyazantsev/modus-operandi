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
                mod.ADR_WORKFLOW,
                str(base / "spec-kit-llm-client" / "adr-pipeline.yml"),
            )
            self.assertEqual(
                mod.REVIEW_WORKFLOW,
                str(base / "spec-kit-llm-client" / "review-pipeline.yml"),
            )
            self.assertEqual(
                mod.CONFIG, str(base / "spec-kit-llm-client" / "config.yml")
            )
            self.assertEqual(
                mod.INSTALL_PATH_FILE,
                base / "spec-kit-llm-client" / "install-path.txt",
            )
