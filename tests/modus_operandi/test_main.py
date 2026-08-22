"""Unit tests for the launcher.s main() and the bootstrap (bootstrap.ensure_installed)."""

import io
import tempfile
import unittest
from unittest import mock

from modus_operandi import InstallError, __version__, bootstrap, installer, verify

from .helpers import load_modus_operandi


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_modus_operandi(self.xdg)

    def test_main_execs_run_pipeline(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(mod.bootstrap, "ensure_installed", return_value=0),
            mock.patch.object(mod.os, "execv") as execv,
        ):
            mod.main(["task", "add a dark mode toggle"])
        execv.assert_called_once()
        self.assertEqual(
            execv.call_args.args[1],
            [mod.RUN_PIPELINE, mod.TASK_WORKFLOW, "-i", "task=add a dark mode toggle"],
        )

    def test_main_bootstraps_before_exec(self) -> None:
        # A failed bootstrap aborts the run: no execv, exit 1.
        mod = self.mod
        with (
            mock.patch.object(mod.bootstrap, "ensure_installed", return_value=1),
            mock.patch.object(mod.os, "execv") as execv,
        ):
            rc = mod.main(["review"])
        self.assertEqual(rc, 1)
        execv.assert_not_called()

    def test_main_help_exit_zero_without_bootstrap(self) -> None:
        mod = self.mod
        captured = io.StringIO()
        with (
            mock.patch("sys.stdout", captured),
            mock.patch.object(mod.bootstrap, "ensure_installed") as ensure,
        ):
            rc = mod.main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("Usage:", captured.getvalue())
        ensure.assert_not_called()

    def test_main_no_args_exit_nonzero(self) -> None:
        mod = self.mod
        with (
            mock.patch("sys.stderr", io.StringIO()) as err,
            mock.patch.object(mod.bootstrap, "ensure_installed") as ensure,
        ):
            rc = mod.main([])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())
        ensure.assert_not_called()

    def test_main_unknown_subcommand_exit_nonzero(self) -> None:
        mod = self.mod
        with (
            mock.patch("sys.stderr", io.StringIO()) as err,
            mock.patch.object(mod.bootstrap, "ensure_installed") as ensure,
        ):
            rc = mod.main(["frobnicate"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())
        ensure.assert_not_called()

    def test_main_dangling_input_exit_nonzero(self) -> None:
        mod = self.mod
        for argv in (["task", "feat", "-i"], ["review", "-i"]):
            with (
                self.subTest(argv=argv),
                mock.patch("sys.stderr", io.StringIO()) as err,
                mock.patch.object(mod.bootstrap, "ensure_installed") as ensure,
            ):
                rc = mod.main(argv)
            self.assertEqual(rc, 1)
            self.assertIn("Usage:", err.getvalue())
            ensure.assert_not_called()

    def test_main_execv_failure_reports_error(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(mod.bootstrap, "ensure_installed", return_value=0),
            mock.patch.object(mod.os, "execv", side_effect=OSError("no such file")),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["review"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())

    def test_main_edit_bootstraps_then_runs_edit(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(mod.bootstrap, "ensure_installed", return_value=0),
            mock.patch.object(mod, "_run_edit", return_value=0) as run_edit,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 0)
        run_edit.assert_called_once_with(mod.CONFIG, mod._LAYOUT)

    def test_main_edit_bootstrap_failure_aborts(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(mod.bootstrap, "ensure_installed", return_value=1),
            mock.patch.object(mod, "_run_edit") as run_edit,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 1)
        run_edit.assert_not_called()

    def test_main_edit_propagates_edit_exit_code(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(mod.bootstrap, "ensure_installed", return_value=0),
            mock.patch.object(mod, "_run_edit", return_value=3),
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 3)

    def test_main_uninstall_skips_bootstrap_and_passes_yes(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(mod.bootstrap, "ensure_installed") as ensure,
            mock.patch.object(mod.uninstall, "do_uninstall", return_value=0) as uninstall,
        ):
            rc = mod.main(["uninstall", "--yes"])
        self.assertEqual(rc, 0)
        ensure.assert_not_called()
        uninstall.assert_called_once_with(mod._LAYOUT, True)

    def test_main_uninstall_without_yes(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(mod.bootstrap, "ensure_installed") as ensure,
            mock.patch.object(mod.uninstall, "do_uninstall", return_value=1) as uninstall,
        ):
            rc = mod.main(["uninstall"])
        self.assertEqual(rc, 1)
        ensure.assert_not_called()
        uninstall.assert_called_once_with(mod._LAYOUT, False)


class EnsureInstalledTest(unittest.TestCase):
    """bootstrap.ensure_installed: the marker, the status lines and errors."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_modus_operandi(self.xdg)
        self.marker = self.mod._LAYOUT["install_version"]

    def test_fresh_install_renders_and_prints_one_status_line(self) -> None:
        mod = self.mod
        captured = io.StringIO()
        with (
            mock.patch.object(verify, "check_prerequisites") as check,
            mock.patch.object(installer, "apply", return_value=(False, {})) as apply,
            mock.patch("sys.stdout", captured),
        ):
            rc = bootstrap.ensure_installed(mod._LAYOUT)
        self.assertEqual(rc, 0)
        check.assert_called_once_with(mod._LAYOUT)
        apply.assert_called_once_with(mod._LAYOUT)
        self.assertEqual(
            captured.getvalue().strip(),
            f"modus-operandi: installed to {mod._LAYOUT['config_dir']}",
        )

    def test_stale_version_renders_and_prints_updated(self) -> None:
        mod = self.mod
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("0.0.9", encoding="utf-8")
        captured = io.StringIO()
        with (
            mock.patch.object(verify, "check_prerequisites"),
            mock.patch.object(installer, "apply", return_value=(False, {})),
            mock.patch("sys.stdout", captured),
        ):
            rc = bootstrap.ensure_installed(mod._LAYOUT)
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue().strip(), f"modus-operandi: updated to {__version__}")

    def test_current_install_prints_nothing(self) -> None:
        mod = self.mod
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(__version__, encoding="utf-8")
        captured = io.StringIO()
        with (
            mock.patch.object(verify, "check_prerequisites") as check,
            mock.patch.object(installer, "apply", return_value=(False, {})) as apply,
            mock.patch("sys.stdout", captured),
        ):
            rc = bootstrap.ensure_installed(mod._LAYOUT)
        self.assertEqual(rc, 0)
        check.assert_not_called()
        apply.assert_not_called()
        self.assertEqual(captured.getvalue(), "")

    def test_prerequisite_failure_reports_error(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(
                verify, "check_prerequisites", side_effect=InstallError("opencode not found")
            ),
            mock.patch.object(installer, "apply") as apply,
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = bootstrap.ensure_installed(mod._LAYOUT)
        self.assertEqual(rc, 1)
        apply.assert_not_called()
        self.assertIn("error: opencode not found", err.getvalue())

    def test_apply_failure_reports_error(self) -> None:
        mod = self.mod
        with (
            mock.patch.object(verify, "check_prerequisites"),
            mock.patch.object(installer, "apply", side_effect=InstallError("bad config")),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = bootstrap.ensure_installed(mod._LAYOUT)
        self.assertEqual(rc, 1)
        self.assertIn("error: bad config", err.getvalue())
