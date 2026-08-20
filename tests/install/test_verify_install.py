"""Tests for verify.verify_install."""

from unittest import mock

from spec_run import InstallError, config, paths, proc, tool_discovery, verify

from .fake_result import FakeResult
from .install_helpers import which_fake
from .installer_test_case import InstallerTestCase


def _opencode_cfg() -> dict:
    """A cfg with the opencode section present (agent files are required)."""
    return config.validate_config(
        config.apply_defaults(
            {
                "opencode": {
                    "models": {
                        "planner": {"provider": "p", "model": "m"},
                        "executor": {"provider": "p", "model": "m"},
                    }
                }
            }
        )
    )


class VerifyInstallTest(InstallerTestCase):
    """verify.verify_install: all errors are collected, and the specify
    syntax probe degrades to the documented message when specify is off
    PATH."""

    def test_verify_collects_all_errors(self):
        layout = paths.build_paths(str(self.home))
        (self.home / ".config/opencode/agent").mkdir(parents=True)
        run_agent = self.home / ".config/opencode/scripts/run-agent.sh"
        run_agent.parent.mkdir(parents=True)
        run_agent.touch()
        run_agent.chmod(0o755)

        def run_fake(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "info"]:
                return FakeResult(1, "", "Error: Required input 'feature' not provided.\n")
            if cmd[-3:] == ["opencode", "agent", "list"]:
                return FakeResult(0, "build (primary)\n")
            return FakeResult(0)

        with (
            mock.patch.object(proc, "run", side_effect=run_fake),
            self.assertRaises(InstallError) as cm,
        ):
            verify.verify_install(layout, _opencode_cfg())
        err = str(cm.exception)
        self.assertIn("planner", err)
        self.assertIn("executor", err)
        self.assertIn("save_adr.py", err)
        self.assertIn("check_review.py", err)
        self.assertIn("adr_utils.py", err)

    def test_verify_skips_opencode_checks_for_cursor_backend(self):
        # With backend: cursor and no opencode section, the missing opencode
        # agent files and the `opencode agent list` check are not errors; the
        # shared script checks still run.
        layout = paths.build_paths(str(self.home))
        (self.home / ".config/opencode/scripts").mkdir(parents=True)
        run_agent = self.home / ".config/opencode/scripts/run-agent.sh"
        run_agent.touch()
        run_agent.chmod(0o755)

        cfg = config.validate_config(
            config.apply_defaults(
                {
                    "backend": "cursor",
                    "cursor": {
                        "models": {
                            "planner": {"model": "composer-2"},
                            "executor": {"model": "composer-2"},
                        }
                    },
                }
            )
        )
        errors = verify.check_files(layout, cfg)
        self.assertNotIn("generated agent missing", " | ".join(errors))
        self.assertTrue(any("save_adr.py" in e for e in errors))
        self.assertEqual(verify.check_agents_visible(layout, cfg), [])

    def test_verify_workflow_syntax_specify_off_path(self):
        self.assertEqual(self.install(), 0)
        layout = paths.build_paths(str(self.home))
        cfg = config.validate_config(
            config.apply_defaults(config.load_config(layout["config"]))
        )

        def which_off_specify(name):
            if name == "specify":
                return None
            return which_fake(name)

        with (
            mock.patch.object(tool_discovery, "find_in_path", side_effect=which_off_specify),
            self.assertRaises(InstallError) as cm,
        ):
            verify.verify_install(layout, cfg)
        err = str(cm.exception)
        self.assertIn("'specify' not found on PATH", err)
