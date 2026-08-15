"""Unit tests for main() delivering the installed config at runtime."""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import FakeProc, load_run_pipeline, point_config_at


class ConfigDeliveryTest(unittest.TestCase):
    """main() delivers the installed config at runtime: state_dir/adr_dir as
    -i inputs, use_serve as the SKLC_ATTACH_FLAG env, human_gates as the
    adr_verdict input presence."""

    def _popen_args(self, mod, tmp, **workflow_overrides):
        point_config_at(mod, tmp, **workflow_overrides)
        captured = {}
        with (
            mock.patch.object(Path, "cwd", return_value=Path(tmp)),
            mock.patch(
                "subprocess.Popen",
                side_effect=lambda *a, **kw: captured.update(a=kw.get("env", {}))
                or FakeProc(["Run ID: abc12345"], 0, **kw),
            ),
            mock.patch.object(sys, "argv", ["run-pipeline.py", "adr-pipeline"]),
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stdin.isatty", return_value=False),
            mock.patch.object(mod, "notify"),
        ):
            rc = mod.main()
        self.assertEqual(rc, 0)
        return captured["a"]

    def test_state_dir_and_adr_dir_passed_as_inputs(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp, state_dir="meta", adr_dir="docs")
            captured = {}

            def fake_popen(*a, **kw):
                captured["cmd"] = a[0]
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                mock.patch.object(sys, "argv", ["run-pipeline.py", "adr-pipeline"]),
                mock.patch("sys.stdout", io.StringIO()),
                mock.patch("sys.stdin.isatty", return_value=False),
                mock.patch.object(mod, "notify"),
            ):
                mod.main()
        self.assertIn("-i", captured["cmd"])
        self.assertIn("state_dir=meta", captured["cmd"])
        self.assertIn("adr_dir=docs", captured["cmd"])

    def test_use_serve_sets_attach_flag_env(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            env = self._popen_args(mod, tmp, use_serve=True)
        self.assertEqual(env["SKLC_ATTACH_FLAG"], "--attach http://localhost:4096")
        self.assertTrue(env["SKLC_SCRIPTS_DIR"])
        self.assertEqual(env["SKLC_SCRIPTS_DIR"], str(Path(mod.__file__).parent))

    def test_state_dir_env_matches_configured_value(self):
        # run-agent.sh resolves its sessions/logs dir from SKLC_STATE_DIR, so
        # the wrapper must export the configured state_dir for the steps.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            env = self._popen_args(mod, tmp, state_dir="meta")
        self.assertEqual(env["SKLC_STATE_DIR"], "meta")

    def test_use_serve_false_sets_empty_attach_flag(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            env = self._popen_args(mod, tmp, use_serve=False)
        self.assertEqual(env["SKLC_ATTACH_FLAG"], "")

    def test_human_gates_true_passes_empty_adr_verdict(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp, human_gates=True)
            captured = {}

            def fake_popen(*a, **kw):
                captured["cmd"] = a[0]
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                mock.patch.object(sys, "argv", ["run-pipeline.py", "adr-pipeline"]),
                mock.patch("sys.stdout", io.StringIO()),
                mock.patch("sys.stdin.isatty", return_value=False),
                mock.patch.object(mod, "notify"),
            ):
                mod.main()
        self.assertIn("-i", captured["cmd"])
        self.assertIn("adr_verdict=", captured["cmd"])

    def test_human_gates_false_omits_adr_verdict(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            point_config_at(mod, tmp, human_gates=False)
            captured = {}

            def fake_popen(*a, **kw):
                captured["cmd"] = a[0]
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                mock.patch.object(sys, "argv", ["run-pipeline.py", "adr-pipeline"]),
                mock.patch("sys.stdout", io.StringIO()),
                mock.patch("sys.stdin.isatty", return_value=False),
                mock.patch.object(mod, "notify"),
            ):
                mod.main()
        self.assertNotIn("adr_verdict=", captured["cmd"])

    def test_missing_config_degrades_to_defaults(self):
        # No config.yml (e.g. hand-invoked wrapper): defaults are used and
        # the run proceeds.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            captured = {}

            def fake_popen(*a, **kw):
                captured["cmd"] = a[0]
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch.object(
                    mod, "CONFIG_PATH", Path(tmp) / "does-not-exist.yml"
                ),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                mock.patch.object(sys, "argv", ["run-pipeline.py", "adr-pipeline"]),
                mock.patch("sys.stdout", io.StringIO()),
                mock.patch("sys.stdin.isatty", return_value=False),
                mock.patch.object(mod, "notify"),
            ):
                rc = mod.main()
        self.assertEqual(rc, 0)
        self.assertIn("state_dir=.workflow", captured["cmd"])
        self.assertIn("adr_verdict=", captured["cmd"])  # human_gates default True
