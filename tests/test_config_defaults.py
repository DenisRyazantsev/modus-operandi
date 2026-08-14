"""Unit tests for config.apply_defaults."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spec_utils import config


class ApplyDefaultsTest(unittest.TestCase):
    def test_empty_config_gets_defaults(self):
        cfg = config.apply_defaults({})
        self.assertEqual(cfg["workflow"]["state_dir"], ".workflow")
        self.assertEqual(cfg["workflow"]["max_fix_iterations"], 5)
        self.assertEqual(cfg["workflow"]["max_srp_iterations"], 5)
        self.assertEqual(cfg["workflow"]["max_bug_iterations"], 5)
        self.assertEqual(cfg["workflow"]["max_comment_iterations"], 5)
        self.assertEqual(cfg["workflow"]["max_adr_iterations"], 3)
        self.assertEqual(cfg["workflow"]["shell_timeout"], 7200)
        self.assertEqual(cfg["workflow"]["adr_dir"], "architecture")
        self.assertTrue(cfg["workflow"]["human_gates"])
        self.assertFalse(cfg["workflow"]["use_serve"])
        for role in ("planner", "executor"):
            self.assertIn("reasoning", cfg["models"][role])

    def test_none_raw_is_treated_as_empty(self):
        cfg = config.apply_defaults(None)
        self.assertEqual(cfg["models"], {"planner": {"reasoning": "max"},
                                         "executor": {"reasoning": "max"}})

    def test_missing_sections_filled(self):
        cfg = config.apply_defaults({"models": {"planner": {"provider": "p",
                                                            "model": "m"}}})
        self.assertEqual(cfg["models"]["planner"]["reasoning"], "max")
        self.assertEqual(cfg["models"]["executor"], {"reasoning": "max"})
        self.assertIn("state_dir", cfg["workflow"])

    def test_override_reasoning_kept(self):
        cfg = config.apply_defaults(
            {"models": {"planner": {"reasoning": "high"}}}
        )
        self.assertEqual(cfg["models"]["planner"]["reasoning"], "high")

    def test_workflow_partial_override(self):
        cfg = config.apply_defaults({"workflow": {"max_fix_iterations": 9}})
        self.assertEqual(cfg["workflow"]["max_fix_iterations"], 9)
        self.assertEqual(cfg["workflow"]["state_dir"], ".workflow")

    def test_non_mapping_workflow_raises_install_error(self):
        with self.assertRaises(config.InstallError) as cm:
            config.apply_defaults({"workflow": "some-string"})
        self.assertIn("workflow must be a mapping", str(cm.exception))

    def test_non_mapping_models_raises_install_error(self):
        with self.assertRaises(config.InstallError) as cm:
            config.apply_defaults({"models": "some-string"})
        self.assertIn("models must be a mapping", str(cm.exception))

    def test_non_mapping_models_role_raises_install_error(self):
        for role in ("planner", "executor"):
            with self.assertRaises(config.InstallError) as cm:
                config.apply_defaults({"models": {role: 123}})
            self.assertIn(f"models.{role} must be a mapping", str(cm.exception))

    def test_non_mapping_top_level_raises_install_error(self):
        # A config.yml whose root is valid YAML but not a mapping (a bare
        # scalar or a list) must fail with a clean InstallError, not an
        # unhandled TypeError from dict(raw).
        for raw in (42, [1, 2, 3]):
            with self.assertRaises(config.InstallError) as cm:
                config.apply_defaults(raw)
            self.assertIn("top-level must be a mapping", str(cm.exception))

    def test_load_config_non_mapping_root_raises_install_error(self):
        for content in ("42\n", "- a\n- b\n"):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.yml"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(config.InstallError) as cm:
                    config.load_config(path)
                self.assertIn("top-level must be a mapping", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
