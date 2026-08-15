"""Tests for install-time prerequisite checks."""

from unittest import mock

from spec_utils import proc, versions

from .fake_result import FakeResult
from .install_helpers import make_run, which_fake
from .installer_test_case import InstallerTestCase


class PrerequisitesTest(InstallerTestCase):
    """Install-time prerequisite checks: missing tools, the specify workflow
    syntax check tolerating message variations, and specify discovery."""

    def test_missing_opencode_fails_with_message(self):
        def which(name):
            if name == "opencode":
                return None
            return which_fake(name)

        rc, err = self.run_main(["--home", str(self.home)], which=which)
        self.assertEqual(rc, 1)
        self.assertIn("opencode not found", err)

    def test_workflow_check_tolerates_stdout_message(self):
        def run_stdout(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(1, "Error: Required input 'feature' not provided.\n", "")
            return make_run()(cmd, cwd, env, check)

        with mock.patch.object(proc, "run", side_effect=run_stdout):
            self.assertEqual(self.install(), 0)

    def test_workflow_check_tolerates_lowercase_message(self):
        def run_lower(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(1, "", "error: required input 'feature' not provided.\n")
            return make_run()(cmd, cwd, env, check)

        with mock.patch.object(proc, "run", side_effect=run_lower):
            self.assertEqual(self.install(), 0)

    def test_specify_candidates_finds_local_bin(self):
        (self.home / ".local" / "bin").mkdir(parents=True)
        (self.home / ".local" / "bin" / "specify").touch()
        with mock.patch.object(versions.Path, "home", return_value=self.home):
            self.assertIn(
                str(self.home / ".local/bin/specify"),
                versions._specify_candidates(),
            )
