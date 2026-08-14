"""Unit tests for config.apply_defaults."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklc import config


class ApplyDefaultsTest(unittest.TestCase):
    def test_empty_config_gets_defaults(self):
        cfg = config.apply_defaults({})
        self.assertEqual(cfg["workflow"]["state_dir"], ".workflow")
        self.assertEqual(cfg["workflow"]["max_fix_iterations"], 5)
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


if __name__ == "__main__":
    unittest.main()
