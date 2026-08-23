"""Unit tests for main() delivering the installed config at runtime."""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.env_sandbox import argv, cwd, stdin, stdout

from .helpers import FakeProc, load_run_pipeline, point_config_at


class ConfigDeliveryTest(unittest.TestCase):
    """main() delivers the installed config at runtime: state_dir/adr_dir as
    -i inputs, use_serve as the MO_ATTACH_FLAG env, human_gates as the
    adr_verdict input presence."""

    def _popen_args(self, mod: Any, tmp: str, **workflow_overrides: Any) -> Any:
        point_config_at(mod, tmp, **workflow_overrides)
        captured: dict[str, Any] = {}
        with (
            cwd(tmp),
            mock.patch(
                "subprocess.Popen",
                side_effect=lambda *a, **kw: (
                    captured.update(a=kw.get("env", {})) or FakeProc(["Run ID: abc12345"], 0, **kw)
                ),
            ),
            argv(["run-pipeline.py", "adr-pipeline"]),
            stdout(io.StringIO()),
            stdin(io.StringIO()),
        ):
            rc = mod.main()
        self.assertEqual(rc, 0)
        return captured["a"]

    def test_state_dir_and_adr_dir_passed_as_inputs(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp, state_dir="meta", adr_dir="docs")
            captured: dict[str, Any] = {}

            def fake_popen(*a: object, **kw: object) -> FakeProc:
                captured["cmd"] = a[0]
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                cwd(tmp),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                argv(["run-pipeline.py", "adr-pipeline"]),
                stdout(io.StringIO()),
                stdin(io.StringIO()),
            ):
                mod.main()
        self.assertIn("-i", captured["cmd"])
        self.assertIn("state_dir=meta", captured["cmd"])
        self.assertIn("adr_dir=docs", captured["cmd"])

    def test_use_serve_sets_attach_flag_env(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            env = self._popen_args(mod, tmp, use_serve=True)
        self.assertEqual(env["MO_ATTACH_FLAG"], "--attach http://localhost:4096")
        self.assertTrue(env["MO_SCRIPTS_DIR"])
        self.assertEqual(env["MO_SCRIPTS_DIR"], str(Path(mod.__file__ or "").parent))

    def test_state_dir_env_matches_configured_value(self) -> None:
        # run-agent.sh resolves its sessions/logs dir from MO_STATE_DIR, so
        # the wrapper must export the configured state_dir for the steps.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            env = self._popen_args(mod, tmp, state_dir="meta")
        self.assertEqual(env["MO_STATE_DIR"], "meta")

    def test_use_serve_false_sets_empty_attach_flag(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            env = self._popen_args(mod, tmp, use_serve=False)
        self.assertEqual(env["MO_ATTACH_FLAG"], "")

    def test_human_gates_true_passes_empty_adr_verdict(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp, human_gates=True)
            captured: dict[str, Any] = {}

            def fake_popen(*a: object, **kw: object) -> FakeProc:
                captured["cmd"] = a[0]
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                cwd(tmp),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                argv(["run-pipeline.py", "adr-pipeline"]),
                stdout(io.StringIO()),
                stdin(io.StringIO()),
            ):
                mod.main()
        self.assertIn("-i", captured["cmd"])
        self.assertIn("adr_verdict=", captured["cmd"])

    def test_human_gates_false_omits_adr_verdict(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp, human_gates=False)
            captured: dict[str, Any] = {}

            def fake_popen(*a: object, **kw: object) -> FakeProc:
                captured["cmd"] = a[0]
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                cwd(tmp),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                argv(["run-pipeline.py", "adr-pipeline"]),
                stdout(io.StringIO()),
                stdin(io.StringIO()),
            ):
                mod.main()
        self.assertNotIn("adr_verdict=", captured["cmd"])

    def test_missing_config_degrades_to_defaults(self) -> None:
        # No config.yml (e.g. hand-invoked wrapper): defaults are used and
        # the run proceeds.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            captured: dict[str, Any] = {}

            def fake_popen(*a: object, **kw: object) -> FakeProc:
                captured["cmd"] = a[0]
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                cwd(tmp),
                mock.patch.object(mod, "CONFIG_PATH", Path(tmp) / "does-not-exist.yml"),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                argv(["run-pipeline.py", "adr-pipeline"]),
                stdout(io.StringIO()),
                stdin(io.StringIO()),
            ):
                rc = mod.main()
        self.assertEqual(rc, 0)
        self.assertIn("state_dir=.workflow", captured["cmd"])
        self.assertIn("adr_verdict=", captured["cmd"])  # human_gates default True

    def test_backend_flag_exports_backend_and_models(self) -> None:
        # The leading global flag (as modus-operandi forwards it) overrides the
        # config backend for the run and is stripped from the specify argv.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp)
            captured: dict[str, Any] = {}

            def fake_popen(*a: object, **kw: object) -> FakeProc:
                captured["cmd"] = a[0]
                captured["env"] = kw.get("env", {})
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                cwd(tmp),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                mock.patch.object(
                    sys, "argv", ["run-pipeline.py", "--backend", "cursor", "adr-pipeline"]
                ),
                stdout(io.StringIO()),
                stdin(io.StringIO()),
            ):
                rc = mod.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured["env"]["MO_BACKEND"], "cursor")
        self.assertNotIn("--backend", captured["cmd"])
        self.assertEqual(captured["cmd"][0], "specify")

    def test_backend_flag_invalid_value_fails(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp)
            with (
                mock.patch.object(
                    sys, "argv", ["run-pipeline.py", "--backend", "bogus", "adr-pipeline"]
                ),
                mock.patch("sys.stderr", io.StringIO()) as stderr,
            ):
                rc = mod.main()
        self.assertEqual(rc, 1)
        self.assertIn("invalid --backend value 'bogus'", stderr.getvalue())

    def test_backend_flag_without_value_fails(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp)
            with (
                mock.patch.object(sys, "argv", ["run-pipeline.py", "--backend"]),
                mock.patch("sys.stderr", io.StringIO()) as stderr,
            ):
                rc = mod.main()
        self.assertEqual(rc, 1)
        self.assertIn("--backend requires a value", stderr.getvalue())
