"""Tests for verify.verify_install."""

from unittest import mock

from spec_utils import InstallError, paths, proc, tool_discovery, verify, versions

from .fake_result import FakeResult
from .install_helpers import which_fake
from .installer_test_case import InstallerTestCase


class VerifyInstallTest(InstallerTestCase):
    """verify.verify_install: all errors are collected, and specify-version
    failures degrade to the documented messages."""

    def test_verify_collects_all_errors(self):
        layout = paths.build_paths(str(self.home))
        (self.home / ".config/opencode/agent").mkdir(parents=True)
        run_agent = self.home / ".config/opencode/scripts/run-agent.sh"
        run_agent.parent.mkdir(parents=True)
        run_agent.touch()
        run_agent.chmod(0o755)

        def run_fake(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(1, "", "Error: Required input 'feature' not provided.\n")
            if cmd[-3:] == ["opencode", "agent", "list"]:
                return FakeResult(0, "build (primary)\n")
            return FakeResult(0)

        with (
            mock.patch.object(proc, "run", side_effect=run_fake),
            self.assertRaises(InstallError) as cm,
        ):
            verify.verify_install(layout)
        err = str(cm.exception)
        self.assertIn("planner", err)
        self.assertIn("executor", err)
        self.assertIn("save_adr.py", err)
        self.assertIn("check_review.py", err)
        self.assertIn("adr_utils.py", err)

    def test_verify_workflow_syntax_specify_off_path(self):
        self.assertEqual(self.install(), 0)
        layout = paths.build_paths(str(self.home))

        def which_off_specify(name):
            if name == "specify":
                return None
            return which_fake(name)

        with (
            mock.patch.object(tool_discovery, "find_in_path", side_effect=which_off_specify),
            mock.patch.object(
                versions,
                "latest_specify_version",
                return_value=((0, 16), "/home/u/.local/bin/specify"),
            ),
            self.assertRaises(InstallError) as cm,
        ):
            verify.verify_install(layout)
        err = str(cm.exception)
        self.assertIn("'specify' not found on PATH", err)
        self.assertIn("/home/u/.local/bin/specify", err)
