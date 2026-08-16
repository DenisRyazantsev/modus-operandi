"""Unit tests for the backend env exports of build_specify_invocation.

build_specify_invocation exports SKLC_BACKEND plus the role models of the
active backend to the workflow steps, so run-agent.sh/name-task.sh know which
backend and which per-role model to use.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class BuildSpecifyInvocationBackendTest(unittest.TestCase):
    """build_specify_invocation exports the backend and the role models."""

    def _invoke(self, mod, tmp, cfg, cli_backend=None):
        with mock.patch.object(Path, "cwd", return_value=Path(tmp)):
            return mod.build_specify_invocation(
                cfg, "adr-pipeline", [], cli_backend=cli_backend
            )

    def _cfg(self, **extra) -> dict:
        cfg = json.loads(json.dumps(OPENCODE_CFG))
        cfg.update(extra)
        return cfg

    def test_default_exports_opencode_and_models(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            _, env, _, _ = self._invoke(mod, tmp, self._cfg())
        self.assertEqual(env["SKLC_BACKEND"], "opencode")
        self.assertEqual(env["SKLC_PLANNER_MODEL"], "deepseek-v4-pro")
        self.assertEqual(env["SKLC_EXECUTOR_MODEL"], "deepseek-v4-flash")

    def test_cursor_config_exports_cursor_models(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            _, env, _, _ = self._invoke(
                mod, tmp, json.loads(json.dumps(CURSOR_CFG)) | {"backend": "cursor"}
            )
        self.assertEqual(env["SKLC_BACKEND"], "cursor")
        self.assertEqual(env["SKLC_PLANNER_MODEL"], "planner-slug")
        self.assertEqual(env["SKLC_EXECUTOR_MODEL"], "executor-slug")

    def test_cli_backend_overrides_config(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            _, env, _, _ = self._invoke(mod, tmp, self._cfg(), cli_backend="cursor")
        self.assertEqual(env["SKLC_BACKEND"], "cursor")
        # No cursor section in the config: the model exports degrade to "".
        self.assertEqual(env["SKLC_PLANNER_MODEL"], "")
        self.assertEqual(env["SKLC_EXECUTOR_MODEL"], "")

    def test_legacy_models_export_opencode_models(self):
        mod = load_run_pipeline()
        legacy = {"models": {"planner": {"model": "legacy-pro"},
                             "executor": {"model": "legacy-flash"}}}
        with tempfile.TemporaryDirectory() as tmp:
            _, env, _, _ = self._invoke(mod, tmp, legacy)
        self.assertEqual(env["SKLC_BACKEND"], "opencode")
        self.assertEqual(env["SKLC_PLANNER_MODEL"], "legacy-pro")
        self.assertEqual(env["SKLC_EXECUTOR_MODEL"], "legacy-flash")


if __name__ == "__main__":
    unittest.main()
