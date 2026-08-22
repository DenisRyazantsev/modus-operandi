"""Unit tests for config.apply_defaults."""

import tempfile
import unittest
from pathlib import Path

from modus_operandi import config


class ApplyDefaultsTest(unittest.TestCase):
    def test_empty_config_gets_defaults(self) -> None:
        cfg = config.apply_defaults({})
        self.assertEqual(cfg["backend"], "opencode")
        self.assertEqual(cfg["workflow"]["state_dir"], ".workflow")
        self.assertEqual(cfg["workflow"]["max_fix_iterations"], 5)
        self.assertEqual(cfg["workflow"]["max_srp_iterations"], 5)
        self.assertEqual(cfg["workflow"]["max_bug_iterations"], 5)
        self.assertEqual(cfg["workflow"]["max_comment_iterations"], 5)
        self.assertEqual(cfg["workflow"]["max_implement_iterations"], 2)
        self.assertEqual(cfg["workflow"]["max_questions_iterations"], 3)
        self.assertEqual(cfg["workflow"]["shell_timeout"], 7200)
        self.assertEqual(cfg["workflow"]["adr_dir"], "architecture")
        self.assertTrue(cfg["workflow"]["human_gates"])
        self.assertFalse(cfg["workflow"]["use_serve"])
        # The motivation loop is effectively unlimited since ADR-0011: its
        # ceiling is a workflow literal, so no config key exists for it.
        self.assertNotIn("max_motivation_iterations", cfg["workflow"])
        self.assertNotIn("max_proposal_iterations", cfg["workflow"])
        # Empty config: no backend sections are fabricated (the active
        # backend's models are required by validation instead).
        self.assertNotIn("opencode", cfg)
        self.assertNotIn("cursor", cfg)

    def test_none_raw_is_treated_as_empty(self) -> None:
        cfg = config.apply_defaults(None)
        self.assertEqual(cfg["backend"], "opencode")
        self.assertNotIn("opencode", cfg)
        self.assertNotIn("cursor", cfg)

    def test_legacy_models_fold_into_opencode(self) -> None:
        cfg = config.apply_defaults({"models": {"planner": {"provider": "p", "model": "m"}}})
        self.assertNotIn("models", cfg)
        self.assertEqual(cfg["opencode"]["models"]["planner"]["reasoning"], "max")
        self.assertEqual(cfg["opencode"]["models"]["executor"], {"reasoning": "max"})
        self.assertIn("state_dir", cfg["workflow"])

    def test_explicit_opencode_section_wins_over_legacy_models(self) -> None:
        cfg = config.apply_defaults(
            {
                "models": {"planner": {"provider": "legacy", "model": "old"}},
                "opencode": {"models": {"planner": {"provider": "new", "model": "m"}}},
            }
        )
        self.assertNotIn("models", cfg)
        self.assertEqual(cfg["opencode"]["models"]["planner"]["provider"], "new")

    def test_opencode_reasoning_default_and_override(self) -> None:
        cfg = config.apply_defaults({"opencode": {"models": {"planner": {"reasoning": "high"}}}})
        self.assertEqual(cfg["opencode"]["models"]["planner"]["reasoning"], "high")
        self.assertEqual(cfg["opencode"]["models"]["executor"]["reasoning"], "max")

    def test_cursor_section_structural_defaults(self) -> None:
        cfg = config.apply_defaults({"cursor": {"models": {"planner": {"model": "composer-2"}}}})
        self.assertEqual(cfg["cursor"]["models"]["planner"]["model"], "composer-2")
        self.assertEqual(cfg["cursor"]["models"]["executor"], {})

    def test_opencode_models_complete_predicate(self) -> None:
        # The single predicate shared by render_agents (writes agent files)
        # and check_files (requires them): complete opencode models for both
        # roles, nothing less.
        self.assertFalse(config.opencode_models_complete({}))
        self.assertFalse(config.opencode_models_complete({"opencode": {}}))
        self.assertFalse(config.opencode_models_complete({"cursor": {}}))
        partial = {
            "opencode": {
                "models": {
                    "planner": {"provider": "p", "model": "m"},
                    "executor": {"provider": "p"},
                }
            }
        }
        self.assertFalse(config.opencode_models_complete(partial))
        complete = {
            "opencode": {
                "models": {
                    "planner": {"provider": "p", "model": "m"},
                    "executor": {"provider": "p", "model": "m"},
                }
            }
        }
        self.assertTrue(config.opencode_models_complete(complete))

    def test_workflow_partial_override(self) -> None:
        cfg = config.apply_defaults({"workflow": {"max_fix_iterations": 9}})
        self.assertEqual(cfg["workflow"]["max_fix_iterations"], 9)
        self.assertEqual(cfg["workflow"]["state_dir"], ".workflow")

    def test_non_mapping_workflow_raises_install_error(self) -> None:
        with self.assertRaises(config.InstallError) as cm:
            config.apply_defaults({"workflow": "some-string"})
        self.assertIn("workflow must be a mapping", str(cm.exception))

    def test_non_mapping_opencode_raises_install_error(self) -> None:
        with self.assertRaises(config.InstallError) as cm:
            config.apply_defaults({"opencode": "some-string"})
        self.assertIn("opencode must be a mapping", str(cm.exception))

    def test_non_mapping_opencode_models_raises_install_error(self) -> None:
        for raw in ({"opencode": {"models": 123}}, {"models": 123}):
            with self.assertRaises(config.InstallError) as cm:
                config.apply_defaults(raw)
            self.assertIn("opencode.models must be a mapping", str(cm.exception))

    def test_non_mapping_opencode_models_role_raises_install_error(self) -> None:
        for role in ("planner", "executor"):
            with self.assertRaises(config.InstallError) as cm:
                config.apply_defaults({"opencode": {"models": {role: 123}}})
            self.assertIn(f"opencode.models.{role} must be a mapping", str(cm.exception))

    def test_non_mapping_cursor_raises_install_error(self) -> None:
        with self.assertRaises(config.InstallError) as cm:
            config.apply_defaults({"cursor": "some-string"})
        self.assertIn("cursor must be a mapping", str(cm.exception))

    def test_non_mapping_cursor_models_role_raises_install_error(self) -> None:
        with self.assertRaises(config.InstallError) as cm:
            config.apply_defaults({"cursor": {"models": {"planner": 123}}})
        self.assertIn("cursor.models.planner must be a mapping", str(cm.exception))

    def test_non_mapping_top_level_raises_install_error(self) -> None:
        # A config.yml whose root is valid YAML but not a mapping (a bare
        # scalar or a list) must fail with a clean InstallError, not an
        # unhandled TypeError from dict(raw).
        for raw in (42, [1, 2, 3]):
            with self.assertRaises(config.InstallError) as cm:
                config.apply_defaults(raw)
            self.assertIn("top-level must be a mapping", str(cm.exception))

    def test_load_config_non_mapping_root_raises_install_error(self) -> None:
        for content in ("42\n", "- a\n- b\n"):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.yml"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(config.InstallError) as cm:
                    config.load_config(path)
                self.assertIn("top-level must be a mapping", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
