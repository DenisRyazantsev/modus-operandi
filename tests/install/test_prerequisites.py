"""Tests for install-time prerequisite checks (real tool lookup on PATH)."""

from .installer_test_case import InstallerTestCase


class PrerequisitesTest(InstallerTestCase):
    """Install-time prerequisite checks: missing tools."""

    def test_missing_opencode_fails_with_message(self) -> None:
        rc, err = self.run_main(["--home", str(self.home)], missing=("opencode",))
        self.assertEqual(rc, 1)
        self.assertIn("opencode not found", err)

    def test_missing_cursor_tool_fails_with_message(self) -> None:
        # backend: cursor requires cursor-agent OR agent on PATH; opencode is
        # not required in this mode.
        self.assertEqual(self.install(), 0)
        self.write_config(
            "backend: cursor\n"
            "cursor:\n"
            "  models:\n"
            "    planner:\n"
            "      model: composer-2\n"
            "    executor:\n"
            "      model: composer-2\n"
            "workflow: {}\n"
        )

        rc, err = self.run_main(["--home", str(self.home)], missing=("cursor-agent", "agent"))
        self.assertEqual(rc, 1)
        self.assertIn("cursor-agent (or agent) not found", err)

    def test_cursor_backend_does_not_require_opencode(self) -> None:
        # A cursor-only install succeeds with opencode off PATH: prerequisite
        # checks, agent rendering and the opencode agent checks are skipped.
        self.assertEqual(self.install(), 0)
        self.write_config(
            "backend: cursor\n"
            "cursor:\n"
            "  models:\n"
            "    planner:\n"
            "      model: composer-2\n"
            "    executor:\n"
            "      model: composer-2\n"
            "workflow: {}\n"
        )

        rc, err = self.run_main(["--home", str(self.home)], missing=("opencode",))
        self.assertEqual(rc, 0, err)
