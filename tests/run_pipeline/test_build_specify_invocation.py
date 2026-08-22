"""Unit tests for build_specify_invocation."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.env_sandbox import cwd

from .helpers import DEFAULT_CONFIG, load_run_pipeline


class BuildSpecifyInvocationTest(unittest.TestCase):
    """build_specify_invocation maps config.yml -> specify argv/env (pure).

    main() only orchestrates the run from what this function returns, so the
    config delivery rules are tested here directly.
    """

    def _cfg(self, **workflow_overrides: object) -> dict[str, Any]:
        cfg: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))
        cfg["workflow"].update(workflow_overrides)
        return cfg

    def _invoke(
        self,
        mod: Any,
        tmp: str,
        cfg: dict[str, Any],
        source: str = "adr-pipeline",
        extra: list[str] | None = None,
    ) -> Any:
        with cwd(tmp):
            return mod.build_specify_invocation(cfg, source, extra or [])

    def test_defaults_map_to_inputs_and_env(self) -> None:
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
        self.assertEqual(env["MO_STATE_DIR"], ".workflow")
        self.assertEqual(env["MO_ATTACH_FLAG"], "")
        self.assertEqual(logs_dir, Path(tmp) / ".workflow" / "logs")

    def test_custom_state_dir_and_adr_dir(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, env, state_dir, logs_dir = self._invoke(
                mod, tmp, self._cfg(state_dir="meta", adr_dir="docs")
            )
        self.assertEqual(state_dir, "meta")
        self.assertIn("state_dir=meta", cmd)
        self.assertIn("adr_dir=docs", cmd)
        self.assertEqual(env["MO_STATE_DIR"], "meta")
        self.assertEqual(logs_dir, Path(tmp) / "meta" / "logs")

    def test_use_serve_sets_attach_flag_env(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            _, env, _, _ = self._invoke(mod, tmp, self._cfg(use_serve=True))
        self.assertEqual(env["MO_ATTACH_FLAG"], "--attach http://localhost:4096")

    def test_human_gates_false_omits_adr_verdict(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, _, _ = self._invoke(mod, tmp, self._cfg(human_gates=False))
        self.assertNotIn("adr_verdict=", cmd)

    def test_task_pipeline_passes_motivation_verdict(self) -> None:
        # The task-pipeline gate is the motivation gate (the proposal gate
        # was removed, ADR-0011): with human_gates true the verdict input is
        # passed empty (interactive), and adr_verdict is not passed at all.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, _, _ = self._invoke(mod, tmp, self._cfg(), source="task-pipeline")
        self.assertIn("motivation_verdict=", cmd)
        self.assertNotIn("proposal_verdict=", cmd)
        self.assertNotIn("adr_verdict=", cmd)

    def test_task_pipeline_human_gates_false_omits_verdicts(self) -> None:
        # With human_gates false the default auto-approves the gate, so no
        # verdict inputs are passed.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, _, _ = self._invoke(
                mod, tmp, self._cfg(human_gates=False), source="task-pipeline"
            )
        self.assertNotIn("motivation_verdict=", cmd)
        self.assertNotIn("proposal_verdict=", cmd)
        self.assertNotIn("adr_verdict=", cmd)

    def test_task_pipeline_path_source_is_detected(self) -> None:
        # The source may be a path to the installed workflow, not just the id.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, _, _ = self._invoke(
                mod,
                tmp,
                self._cfg(),
                source="/home/u/.config/modus-operandi/task-pipeline.yml",
            )
        self.assertIn("motivation_verdict=", cmd)
        self.assertNotIn("proposal_verdict=", cmd)
        self.assertNotIn("adr_verdict=", cmd)

    def test_extra_args_are_appended(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, _, _ = self._invoke(
                mod, tmp, self._cfg(), extra=["-i", "feature=build a board"]
            )
        self.assertEqual(cmd[-2:], ["-i", "feature=build a board"])

    def test_scripts_dir_is_wrappers_own_directory(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            _, env, _, _ = self._invoke(mod, tmp, self._cfg())
        self.assertEqual(env["MO_SCRIPTS_DIR"], str(Path(mod.__file__ or "").parent))
