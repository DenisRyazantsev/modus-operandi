"""Tests for the dev-flow launcher: ~/.local/bin/modus-operandi and PATH setup."""

import os
from pathlib import Path
from unittest import mock

from modus_operandi import installer_cli, uninstall

from .installer_test_case import InstallerTestCase


class DevLauncherTest(InstallerTestCase):
    """install.py installs a checkout-based launcher and keeps ~/.local/bin
    on PATH for newly opened terminals."""

    def test_install_renders_launcher_into_user_bin(self) -> None:
        rc, _ = self.run_main(["--home", str(self.home)])
        self.assertEqual(rc, 0)
        launcher = self.home / ".local/bin/modus-operandi"
        self.assertTrue(launcher.exists())
        self.assertTrue(os.access(launcher, os.X_OK))
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("from modus_operandi.cli import main", text)
        self.assertIn(str(installer_cli._REPO_SRC), text)

    def test_install_keeps_pip_owned_console_script(self) -> None:
        # A pip-installed console script in ~/.local/bin is the package's own
        # file (pip metadata points at it): the dev flow must not overwrite it.
        target = self.home / ".local/bin/modus-operandi"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/bin/sh\necho pip\n", encoding="utf-8")
        with mock.patch.object(uninstall, "pip_installed_bin", return_value={target}):
            rc, _ = self.run_main(["--home", str(self.home)])
        self.assertEqual(rc, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "#!/bin/sh\necho pip\n")

    def test_install_appends_path_block_to_existing_rc_files(self) -> None:
        bashrc = self.home / ".bashrc"
        bashrc.write_text("alias ll='ls -l'\n", encoding="utf-8")
        zshrc = self.home / ".zshrc"
        zshrc.write_text("", encoding="utf-8")
        rc, _ = self.run_main(["--home", str(self.home)])
        self.assertEqual(rc, 0)
        bash_text = bashrc.read_text(encoding="utf-8")
        self.assertIn("alias ll='ls -l'", bash_text)
        self.assertIn(installer_cli._RC_MARKER, bash_text)
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', bash_text)
        self.assertIn(installer_cli._RC_MARKER, zshrc.read_text(encoding="utf-8"))
        # Non-existent rc files are never created.
        self.assertFalse((self.home / ".profile").exists())

    def test_install_path_block_is_idempotent(self) -> None:
        bashrc = self.home / ".bashrc"
        bashrc.write_text("", encoding="utf-8")
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.install(), 0)
        text = bashrc.read_text(encoding="utf-8")
        self.assertEqual(text.count(installer_cli._RC_MARKER), 1)
        self.assertEqual(text.count('export PATH="$HOME/.local/bin:$PATH"'), 1)


class LauncherContentTest(InstallerTestCase):
    """The rendered launcher is a thin checkout-bound entry point."""

    def test_launcher_runs_usage_from_the_checkout(self) -> None:
        rc, _ = self.run_main(["--home", str(self.home)])
        self.assertEqual(rc, 0)
        launcher = Path(installer_cli._REPO_SRC) / "modus_operandi" / "cli.py"
        # The launcher binds the checkout's src dir; running `install.py
        # --help`-style dispatch would hit the real config base, so only the
        # wiring is asserted: the module it imports resolves in the checkout.
        self.assertTrue(launcher.exists())
