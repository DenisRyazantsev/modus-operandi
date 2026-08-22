"""Tests for the launcher's main() and the bootstrap (bootstrap.ensure_installed).

The bootstrap and the edit/uninstall flows run against real artifacts: a
real opencode binary on PATH, a real editor script, real config files under
a temp XDG_CONFIG_HOME. The only stub left is os.execv, which cannot run for
real inside the test process (it replaces the current process) — see
workspace.md.
"""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modus_operandi import __version__, bootstrap
from tests.env_sandbox import env, stderr, stdin, stdout

from .helpers import load_modus_operandi


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_modus_operandi(self.xdg)
        self.bin = Path(self.xdg) / "bin"
        self.bin.mkdir()

    def _write_bins(self, *names: str) -> None:
        for name in names:
            path = self.bin / name
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)

    def _path(self, *names: str, host: bool = True) -> str:
        """PATH with the named real binaries; host PATH appended unless host=False."""
        self._write_bins(*names)
        base = str(self.bin)
        return f"{base}:{os.environ.get('PATH', '')}" if host else base

    def _write_editor(self, body: str, name: str = "editor") -> Path:
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def test_execs_run_pipeline(self) -> None:
        # os.execv replaces the process; only its arguments are asserted.
        # Documented in workspace.md.
        mod = self.mod
        with (
            env({"XDG_CONFIG_HOME": self.xdg, "PATH": self._path("opencode", "python3")}),
            mock.patch.object(mod.os, "execv") as execv,
        ):
            mod.main(["task", "add a dark mode toggle"])
        execv.assert_called_once()
        self.assertEqual(
            execv.call_args.args[1],
            [mod.RUN_PIPELINE, mod.TASK_WORKFLOW, "-i", "task=add a dark mode toggle"],
        )
        self.assertTrue(mod._LAYOUT["install_version"].exists())

    def test_bootstraps_before_exec(self) -> None:
        # A failed bootstrap aborts the run: no execv, exit 1. The bootstrap
        # is real (no opencode on PATH), only the execv stub is kept.
        mod = self.mod
        with (
            env({"XDG_CONFIG_HOME": self.xdg, "PATH": self._path("python3", host=False)}),
            mock.patch.object(mod.os, "execv") as execv,
        ):
            rc = mod.main(["review"])
        self.assertEqual(rc, 1)
        execv.assert_not_called()

    def test_execv_failure_reports_error(self) -> None:
        # os.execv raising OSError is reported with the real bootstrap done.
        # The execv stub is documented in workspace.md.
        mod = self.mod
        with (
            env({"XDG_CONFIG_HOME": self.xdg, "PATH": self._path("opencode", "python3")}),
            mock.patch.object(mod.os, "execv", side_effect=OSError("no such file")),
            stderr(io.StringIO()) as err,
        ):
            rc = mod.main(["review"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())

    def test_main_help_exit_zero_without_bootstrap(self) -> None:
        mod = self.mod
        captured = io.StringIO()
        with stdout(captured):
            rc = mod.main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("Usage:", captured.getvalue())
        self.assertFalse(mod._LAYOUT["install_version"].exists())

    def test_main_no_args_exit_nonzero(self) -> None:
        mod = self.mod
        with stderr(io.StringIO()) as err:
            rc = mod.main([])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())
        self.assertFalse(mod._LAYOUT["install_version"].exists())

    def test_main_unknown_subcommand_exit_nonzero(self) -> None:
        mod = self.mod
        with stderr(io.StringIO()) as err:
            rc = mod.main(["frobnicate"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())
        self.assertFalse(mod._LAYOUT["install_version"].exists())

    def test_main_dangling_input_exit_nonzero(self) -> None:
        mod = self.mod
        for argv in (["task", "feat", "-i"], ["review", "-i"]):
            with (
                self.subTest(argv=argv),
                stderr(io.StringIO()) as err,
            ):
                rc = mod.main(argv)
            self.assertEqual(rc, 1)
            self.assertIn("Usage:", err.getvalue())
            self.assertFalse(mod._LAYOUT["install_version"].exists())

    def test_edit_runs_against_real_artifacts(self) -> None:
        # Full edit flow: real bootstrap (fake opencode on PATH), real editor
        # script editing the rendered config, real re-apply. The editor's
        # change (backend: opencode -> cursor) is validated and applied.
        mod = self.mod
        self._write_editor("#!/bin/sh\nsed -i 's/backend: opencode/backend: cursor/' \"$1\"\n")
        captured = io.StringIO()
        with (
            env(
                {
                    "XDG_CONFIG_HOME": self.xdg,
                    "PATH": self._path("opencode", "python3"),
                    "EDITOR": "editor",
                }
            ),
            stdout(captured),
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 0)
        self.assertIn("config applied", captured.getvalue())
        self.assertIn("backend: cursor", Path(mod.CONFIG).read_text(encoding="utf-8"))

    def test_edit_invalid_edit_is_rolled_back(self) -> None:
        # An editor that corrupts the config: apply() fails validation and
        # the pre-edit snapshot is restored, so the invalid content never
        # sticks on disk.
        mod = self.mod
        self._write_editor("#!/bin/sh\nprintf 'backend: [unclosed\\n' > \"$1\"\n")
        with (
            env(
                {
                    "XDG_CONFIG_HOME": self.xdg,
                    "PATH": self._path("opencode", "python3"),
                    "EDITOR": "editor",
                }
            ),
            stderr(io.StringIO()) as err,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 1)
        self.assertIn("config.yml is invalid", err.getvalue())
        self.assertIn("backend: opencode", Path(mod.CONFIG).read_text(encoding="utf-8"))

    def test_edit_editor_exit_code_does_not_gate_apply(self) -> None:
        # The editor's own exit code does not gate the apply: a valid edit
        # closed with a non-zero code is still applied (vim :cq case).
        mod = self.mod
        self._write_editor(
            "#!/bin/sh\nsed -i 's/backend: opencode/backend: cursor/' \"$1\"\nexit 7\n"
        )
        with (
            env(
                {
                    "XDG_CONFIG_HOME": self.xdg,
                    "PATH": self._path("opencode", "python3"),
                    "EDITOR": "editor",
                }
            ),
            stdout(io.StringIO()) as out,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 0)
        self.assertIn("config applied", out.getvalue())

    def test_edit_bootstrap_failure_aborts(self) -> None:
        # No opencode on PATH: the real bootstrap fails and the editor is
        # never launched (the script touches a marker file on execution).
        mod = self.mod
        self._write_editor('#!/bin/sh\ntouch "$1.ran"\n')
        with (
            env(
                {
                    "XDG_CONFIG_HOME": self.xdg,
                    "PATH": self._path("python3", host=False),
                    "EDITOR": "editor",
                }
            ),
            stderr(io.StringIO()) as err,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 1)
        self.assertIn("opencode not found", err.getvalue())
        self.assertFalse(Path(mod.CONFIG + ".ran").exists())

    def test_uninstall_skips_bootstrap_and_passes_yes(self) -> None:
        # Real uninstall: the rendered files are removed from the temp config
        # base; the bootstrap is skipped (no opencode needed).
        mod = self.mod
        self._write_bins("opencode", "python3")
        with env({"XDG_CONFIG_HOME": self.xdg, "PATH": self._path("opencode", "python3")}):
            self.assertEqual(bootstrap.ensure_installed(mod._LAYOUT), 0)
        captured = io.StringIO()
        with (
            env({"XDG_CONFIG_HOME": self.xdg, "PATH": self._path("opencode", "python3")}),
            stdout(captured),
        ):
            rc = mod.main(["uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertFalse(mod._LAYOUT["config_dir"].exists())
        self.assertIn("run `pip uninstall modus-operandi`", captured.getvalue())

    def test_uninstall_without_yes_asks_for_confirmation(self) -> None:
        # "n" aborts and removes nothing; "y" proceeds and removes the files.
        mod = self.mod
        self._write_bins("opencode", "python3")
        with env({"XDG_CONFIG_HOME": self.xdg, "PATH": self._path("opencode", "python3")}):
            self.assertEqual(bootstrap.ensure_installed(mod._LAYOUT), 0)
        with (
            env({"XDG_CONFIG_HOME": self.xdg, "PATH": self._path("opencode", "python3")}),
            stdin(io.StringIO("n\n")),
            stdout(io.StringIO()) as out,
        ):
            rc = mod.main(["uninstall"])
        self.assertEqual(rc, 1)
        self.assertIn("aborted", out.getvalue())
        self.assertTrue(mod._LAYOUT["config_dir"].exists())
        with (
            env({"XDG_CONFIG_HOME": self.xdg, "PATH": self._path("opencode", "python3")}),
            stdin(io.StringIO("y\n")),
        ):
            rc = mod.main(["uninstall"])
        self.assertEqual(rc, 0)
        self.assertFalse(mod._LAYOUT["config_dir"].exists())


class EnsureInstalledTest(unittest.TestCase):
    """bootstrap.ensure_installed: the marker, the status lines and errors.

    The prerequisites check runs against a real opencode binary created on
    PATH; the apply step renders the real package data into the temp config
    base.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_modus_operandi(self.xdg)
        self.marker = self.mod._LAYOUT["install_version"]
        self.bin = Path(self.xdg) / "bin"
        self.bin.mkdir()

    def _with(self, *names: str, host: bool = True) -> dict[str, str]:
        for name in names:
            bin_path = self.bin / name
            bin_path.write_text("#!/bin/sh\nexit 0\n")
            bin_path.chmod(0o755)
        base = str(self.bin)
        path = f"{base}:{os.environ.get('PATH', '')}" if host else base
        return {"XDG_CONFIG_HOME": self.xdg, "PATH": path}

    def test_fresh_install_renders_and_prints_one_status_line(self) -> None:
        captured = io.StringIO()
        with env(self._with("opencode", "python3")), stdout(captured):
            rc = bootstrap.ensure_installed(self.mod._LAYOUT)
        self.assertEqual(rc, 0)
        self.assertEqual(
            captured.getvalue().strip(),
            f"modus-operandi: installed to {self.mod._LAYOUT['config_dir']}",
        )
        self.assertEqual(self.marker.read_text(encoding="utf-8"), __version__)
        self.assertTrue(self.mod._LAYOUT["run_pipeline"].exists())
        self.assertTrue(self.mod._LAYOUT["config"].exists())

    def test_stale_version_renders_and_prints_updated(self) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("0.0.9", encoding="utf-8")
        captured = io.StringIO()
        with env(self._with("opencode", "python3")), stdout(captured):
            rc = bootstrap.ensure_installed(self.mod._LAYOUT)
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue().strip(), f"modus-operandi: updated to {__version__}")

    def test_current_install_prints_nothing(self) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(__version__, encoding="utf-8")
        captured = io.StringIO()
        with env(self._with("opencode", "python3")), stdout(captured):
            rc = bootstrap.ensure_installed(self.mod._LAYOUT)
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")

    def test_prerequisite_failure_reports_error(self) -> None:
        # No opencode on PATH: the real prerequisite check fails and nothing
        # is rendered.
        with env(self._with("python3", host=False)), stderr(io.StringIO()) as err:
            rc = bootstrap.ensure_installed(self.mod._LAYOUT)
        self.assertEqual(rc, 1)
        self.assertIn("error: opencode not found", err.getvalue())
        self.assertFalse(self.marker.exists())

    def test_apply_failure_reports_error(self) -> None:
        # A config with an invalid backend passes the prerequisite check and
        # fails in the real apply (validation), so the marker is never
        # recorded.
        config = self.mod._LAYOUT["config"]
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("backend: nonsense\n", encoding="utf-8")
        with env(self._with("opencode", "python3")), stderr(io.StringIO()) as err:
            rc = bootstrap.ensure_installed(self.mod._LAYOUT)
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())
        self.assertFalse(self.marker.exists())
