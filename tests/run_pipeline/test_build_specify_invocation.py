"""Unit tests for build_specify_invocation."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import DEFAULT_CONFIG, load_run_pipeline


class BuildSpecifyInvocationTest(unittest.TestCase):
    """build_specify_invocation maps config.yml -> specify argv/env (pure).

    main() only orchestrates the run from what this function returns, so the
    config delivery rules are tested here directly.
    """

    def _cfg(self, **workflow_overrides) -> dict:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        cfg["workflow"].update(workflow_overrides)
        return cfg

    def _invoke(self, mod, tmp, cfg, source="adr-pipeline", extra=None):
        with mock.patch.object(Path, "cwd", return_value=Path(tmp)):
            return mod.build_specify_invocation(cfg, source, extra or [])

    def test_defaults_map_to_inputs_and_env(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, env, state_dir, logs_dir = self._invoke(mod, tmp, self._cfg())
        self.assertEqual(state_dir, ".workflow")
        self.assertEqual(
            cmd,
            [
                "specify",
                "workflow",
                "run",
                "adr-pipeline",
                "-i",
                "state_dir=.workflow",
                "-i",
                "adr_dir=architecture",
                "-i",
                "adr_verdict=",
            ],
        )
        self.assertEqual(env["SKLC_STATE_DIR"], ".workflow")
        self.assertEqual(env["SKLC_ATTACH_FLAG"], "")
        self.assertEqual(logs_dir, Path(tmp) / ".workflow" / "logs")

    def test_custom_state_dir_and_adr_dir(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, env, state_dir, logs_dir = self._invoke(
                mod, tmp, self._cfg(state_dir="meta", adr_dir="docs")
            )
        self.assertEqual(state_dir, "meta")
        self.assertIn("state_dir=meta", cmd)
        self.assertIn("adr_dir=docs", cmd)
        self.assertEqual(env["SKLC_STATE_DIR"], "meta")
        self.assertEqual(logs_dir, Path(tmp) / "meta" / "logs")

    def test_use_serve_sets_attach_flag_env(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            _, env, _, _ = self._invoke(mod, tmp, self._cfg(use_serve=True))
        self.assertEqual(env["SKLC_ATTACH_FLAG"], "--attach http://localhost:4096")

    def test_human_gates_false_omits_adr_verdict(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, _, _ = self._invoke(mod, tmp, self._cfg(human_gates=False))
        self.assertNotIn("adr_verdict=", cmd)

    def test_extra_args_are_appended(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, _, _ = self._invoke(
                mod, tmp, self._cfg(), extra=["-i", "feature=build a board"]
            )
        self.assertEqual(cmd[-2:], ["-i", "feature=build a board"])

    def test_scripts_dir_is_wrappers_own_directory(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            _, env, _, _ = self._invoke(mod, tmp, self._cfg())
        self.assertEqual(env["SKLC_SCRIPTS_DIR"], str(Path(mod.__file__).parent))
