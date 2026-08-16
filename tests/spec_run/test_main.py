"""Unit tests for the launcher's main()."""

import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from .helpers import INSTALL_PY, load_spec_run


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_spec_run(self.xdg)

    def _record_install_py(self):
        config_dir = Path(self.xdg) / "spec-kit-llm-client"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "install-path.txt").write_text(INSTALL_PY, encoding="utf-8")

    def test_main_execs_run_pipeline(self):
        mod = self.mod
        with mock.patch.object(mod.os, "execv") as execv:
            mod.main(["adr", "build a kanban board"])
        execv.assert_called_once()
        self.assertEqual(
            execv.call_args.args[1],
            [mod.RUN_PIPELINE, mod.ADR_WORKFLOW, "-i", "feature=build a kanban board"],
        )

    def test_main_help_exit_zero(self):
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            rc = self.mod.main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("Usage:", captured.getvalue())

    def test_main_no_args_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = self.mod.main([])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_unknown_subcommand_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = self.mod.main(["frobnicate"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_adr_without_feature_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = self.mod.main(["adr"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_dangling_input_exit_nonzero(self):
        for argv in (["adr", "feat", "-i"], ["review", "-i"]):
            with self.subTest(argv=argv), mock.patch("sys.stderr", io.StringIO()) as err:
                rc = self.mod.main(argv)
            self.assertEqual(rc, 1)
            self.assertIn("Usage:", err.getvalue())

    def test_main_execv_failure_reports_error(self):
        mod = self.mod
        with (
            mock.patch.object(mod.os, "execv", side_effect=OSError("no such file")),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["review"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())

    def test_main_edit_runs_editor_then_installer(self):
        mod = self.mod
        self._record_install_py()
        calls: list[list[str]] = []

        def fake_run(cmd, check=True):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0)

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            calls, [["nano", mod.CONFIG], [sys.executable, INSTALL_PY, "--apply"]]
        )

    def test_main_edit_propagates_installer_exit_code(self):
        mod = self.mod
        self._record_install_py()
        results = iter(
            [types.SimpleNamespace(returncode=0), types.SimpleNamespace(returncode=3)]
        )

        def fake_run(cmd, check=True):
            return next(results)

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 3)

    def test_main_edit_applies_after_nonzero_editor_exit(self):
        # A user can save a valid edit and still close the editor non-zero
        # (vim :cq, ...); the config must still be re-applied then.
        mod = self.mod
        self._record_install_py()
        calls: list[list[str]] = []
        results = iter(
            [types.SimpleNamespace(returncode=7), types.SimpleNamespace(returncode=0)]
        )

        def fake_run(cmd, check=True):
            calls.append(cmd)
            return next(results)

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            calls, [["nano", mod.CONFIG], [sys.executable, INSTALL_PY, "--apply"]]
        )

    def test_main_edit_editor_start_failure_returns_nonzero(self):
        mod = self.mod
        self._record_install_py()

        def fake_run(cmd, check=True):
            if cmd[0] == "nano":
                raise OSError("no such file")
            return types.SimpleNamespace(returncode=0)

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())

    def test_main_edit_without_recorded_install_py_fails_cleanly(self):
        # The repo clone was moved/deleted: install-path.txt is missing and
        # `edit` must fail with a readable error, not a traceback.
        mod = self.mod
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run") as run,
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 1)
        run.assert_called_once()  # only the editor launch, no --apply
        self.assertIn("install.py", err.getvalue())
        self.assertIn("install-path.txt", err.getvalue())

    def test_main_edit_without_editor_fails_cleanly(self):
        # No editor on PATH and no valid $VISUAL/$EDITOR binary: `edit` must
        # report it instead of launching a missing binary (regression: the
        # unvalidated fallback returned ["vi"] even when vi was absent).
        mod = self.mod
        with (
            mock.patch.dict("os.environ", {"EDITOR": "vim"}, clear=True),
            mock.patch("shutil.which", return_value=None),
            mock.patch("subprocess.run") as run,
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 1)
        run.assert_not_called()
        self.assertIn("editor", err.getvalue())
