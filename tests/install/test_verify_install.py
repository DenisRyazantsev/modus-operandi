"""Tests for verify.verify_install."""

from pathlib import Path
from typing import Any
from unittest import mock

from modus_operandi import InstallError, config, paths, proc, verify
from tests.env_sandbox import env

from .fake_result import FakeResult
from .installer_test_case import InstallerTestCase


def _opencode_cfg() -> dict[str, Any]:
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

    def test_verify_collects_all_errors(self) -> None:
        layout = paths.build_paths(str(self.home))
        (self.home / ".config/opencode/agent").mkdir(parents=True)
        run_agent = self.home / ".config/opencode/scripts/run-agent.sh"
        run_agent.parent.mkdir(parents=True)
        run_agent.touch()
        run_agent.chmod(0o755)

        def run_fake(
            cmd: list[str],
            cwd: str | Path | None = None,
            env: dict[str, str] | None = None,
            check: bool = True,
        ) -> FakeResult:
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
        self.assertIn("reviewer-srp", err)
        self.assertIn("save_adr.py", err)
        self.assertIn("check_review.py", err)
        self.assertIn("adr_utils.py", err)

    def test_verify_skips_opencode_checks_for_cursor_backend(self) -> None:
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

    def test_verify_workflow_syntax_specify_off_path(self) -> None:
        self.assertEqual(self.install(), 0)
        layout = paths.build_paths(str(self.home))
        cfg = config.validate_config(config.apply_defaults(config.load_config(layout["config"])))

        # The real tool lookup on PATH: specify is removed from the temp
        # bin dir, so verify_install reports it as missing.
        with env({"PATH": str(self.bin)}, clear=True):
            (self.bin / "specify").unlink()
            with self.assertRaises(InstallError) as cm:
                verify.verify_install(layout, cfg)
        err = str(cm.exception)
        self.assertIn("'specify' not found on PATH", err)
