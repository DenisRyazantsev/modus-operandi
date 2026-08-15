"""Tests for installed config validation."""


from .installer_test_case import InstallerTestCase


class ConfigValidationTest(InstallerTestCase):
    """The installed config.yml is validated: malformed, placeholder and
    wrongly-typed values are rejected with a clean error, never a traceback."""

    def install_with_capture(self):
        return self.run_main(["--home", str(self.home)])

    def test_placeholder_config_is_rejected(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            "models:\n"
            "  planner:\n"
            "    provider: p\n"
            "    model: m\n"
            "  executor:\n"
            "    provider: <provider>\n"
            "    model: m\n"
            "workflow: {}\n"
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("placeholder", err)

    def test_malformed_config_reports_error_not_traceback(self):
        self.assertEqual(self.install(), 0)
        self.write_config("models: [\n")
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)

    def test_non_mapping_config_root_reports_error_not_traceback(self):
        # A config.yml that is valid YAML but whose top level is not a mapping
        # (a bare scalar or a list) must fail with a clean InstallError, not
        # an unhandled TypeError traceback from dict(raw).
        for content in ("42\n", "- a\n- b\n"):
            with self.subTest(content=content):
                # Restore a valid config first: install() must not proceed
                # over the previous subTest's broken config.
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
                self.assertEqual(self.install(), 0)
                self.write_config(content)
                rc, err = self.install_with_capture()
                self.assertEqual(rc, 1)
                self.assertIn("top-level must be a mapping", err)
                self.assertNotIn("Traceback", err)

    def test_boolean_iteration_values_rejected(self):
        # bool is a subclass of int: `max_fix_iterations: true` used to pass
        # the integer check and render as "max_iterations: True".
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_fix_iterations: 5", "max_fix_iterations: true")
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("max_fix_iterations must be an integer", err)

    def test_boolean_shell_timeout_rejected(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("shell_timeout: 7200", "shell_timeout: true")
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("shell_timeout must be a positive number", err)

    def test_null_state_dir_rejected(self):
        # str(None) is "None", which used to pass the regex and point every
        # workflow step at "None/tasks/...".
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace("state_dir: .workflow", "state_dir: null"))
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("workflow.state_dir must be a string", err)

    def test_non_string_adr_dir_rejected(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("adr_dir: architecture", "adr_dir: 42")
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("workflow.adr_dir must be a string", err)
