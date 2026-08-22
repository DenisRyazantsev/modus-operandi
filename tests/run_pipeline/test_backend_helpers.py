"""Unit tests for the pure backend helpers in run-pipeline.py.

normalize_config / effective_backend / role_model select the active backend
(CLI flag > config > opencode) and map it to the role models, mirroring the
installer's config handling at runtime.
"""

import unittest

from .helpers import load_run_pipeline

OPENCODE_CFG = {
    "opencode": {
        "models": {
            "planner": {"provider": "opencode-go", "model": "deepseek-v4-pro"},
            "executor": {"provider": "opencode-go", "model": "deepseek-v4-flash"},
        }
    }
}

CURSOR_CFG = {
    "cursor": {
        "models": {
            "planner": {"model": "planner-slug"},
            "executor": {"model": "executor-slug"},
        }
    }
}


class BackendSelectionTest(unittest.TestCase):
    """normalize_config / effective_backend / role_model: pure helpers."""

    def test_effective_backend_defaults_to_opencode(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.effective_backend({}, None), "opencode")
        self.assertEqual(mod.effective_backend({"backend": "bogus"}, None), "opencode")

    def test_effective_backend_reads_config(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.effective_backend({"backend": "cursor"}, None), "cursor")

    def test_effective_backend_cli_flag_wins(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.effective_backend({"backend": "opencode"}, "cursor"), "cursor")
        self.assertEqual(mod.effective_backend({"backend": "cursor"}, "opencode"), "opencode")
        # An invalid CLI value degrades to the config/default.
        self.assertEqual(mod.effective_backend({}, "bogus"), "opencode")

    def test_normalize_config_folds_legacy_models(self) -> None:
        mod = load_run_pipeline()
        cfg = mod.normalize_config({"models": {"planner": {"model": "m"}}})
        self.assertNotIn("models", cfg)
        self.assertEqual(cfg["opencode"]["models"]["planner"]["model"], "m")

    def test_normalize_config_keeps_explicit_opencode(self) -> None:
        mod = load_run_pipeline()
        cfg = mod.normalize_config(OPENCODE_CFG)
        self.assertEqual(cfg["opencode"]["models"]["planner"]["model"], "deepseek-v4-pro")

    def test_role_model_by_backend(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.role_model(OPENCODE_CFG, "opencode", "planner"), "deepseek-v4-pro")
        self.assertEqual(mod.role_model(OPENCODE_CFG, "opencode", "executor"), "deepseek-v4-flash")
        self.assertEqual(mod.role_model(CURSOR_CFG, "cursor", "planner"), "planner-slug")
        self.assertEqual(mod.role_model(CURSOR_CFG, "cursor", "executor"), "executor-slug")
        self.assertEqual(mod.role_model(CURSOR_CFG, "opencode", "planner"), "")

    def test_role_model_empty_when_section_missing(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.role_model({}, "cursor", "planner"), "")
        self.assertEqual(mod.role_model({}, "opencode", "planner"), "")


if __name__ == "__main__":
    unittest.main()
