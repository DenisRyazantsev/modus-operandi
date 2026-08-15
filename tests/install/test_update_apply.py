"""Tests for --apply and --update."""

import io
from unittest import mock

from .install_helpers import which_fake
from .installer_test_case import InstallerTestCase


class UpdateApplyTest(InstallerTestCase):
    """--apply re-renders from the existing config and --update reports new
    options; conflicting subcommand flags are rejected up front."""

    def test_flag_conflicts_rejected(self):
        cases = [
            ["--uninstall", "--update"],
            ["--apply", "--uninstall"],
            ["--apply", "--update"],
        ]
        for extra in cases:
            rc, err = self.run_main(["--home", str(self.home), *extra])
            self.assertEqual(rc, 1, extra)
            self.assertIn("error:", err)

    def test_apply_rerenders_from_current_config(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_fix_iterations: 5", "max_fix_iterations: 9")
        )
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            rc = self.run_main(["--home", str(self.home), "--apply"])[0]
        self.assertEqual(rc, 0)
        # --apply is quiet: no status lines, path warning or next-steps.
        self.assertNotIn("Next steps", stdout.getvalue())
        self.assertNotIn("installation verified", stdout.getvalue())
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("max_iterations: 9", workflow)

    def test_apply_invalid_config_fails(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_fix_iterations: 5", "max_fix_iterations: true")
        )
        rc, err = self.run_main(["--home", str(self.home), "--apply"])
        self.assertEqual(rc, 1)
        self.assertIn("max_fix_iterations must be an integer", err)

    def test_apply_skips_prerequisite_checks(self):
        # --apply re-renders from the existing config without the install-time
        # python3/opencode presence checks, so it works even when opencode is
        # not on PATH (the verify subprocesses still run, faked here).
        self.assertEqual(self.install(), 0)

        def which_no_opencode(name):
            if name == "opencode":
                return None
            return which_fake(name)

        rc, err = self.run_main(["--home", str(self.home), "--apply"], which=which_no_opencode)
        self.assertEqual(rc, 0, err)

    def test_update_reports_new_options(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            "models:\n"
            "  planner:\n"
            "    provider: p\n"
            "    model: m\n"
            "  executor:\n"
            "    provider: p\n"
            "    model: m\n"
            "workflow: {}\n"
        )
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            rc = self.run_main(["--home", str(self.home), "--update"])[0]
        self.assertEqual(rc, 0)
        out = stdout.getvalue()
        self.assertIn("new options available", out)
        self.assertIn("workflow.max_srp_iterations", out)
