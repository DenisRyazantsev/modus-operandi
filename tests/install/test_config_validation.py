"""Tests for installed config validation."""

from .installer_test_case import InstallerTestCase

VALID_BASE = (
    "models:\n"
    "  planner:\n"
    "    provider: p\n"
    "    model: m\n"
    "  executor:\n"
    "    provider: p\n"
    "    model: m\n"
    "workflow: {}\n"
)


class ConfigValidationTest(InstallerTestCase):
    """The installed config.yml is validated: malformed, placeholder and
    wrongly-typed values are rejected with a clean error, never a traceback."""

    def install_with_capture(self) -> tuple[int, str]:
        return self.run_main(["--home", str(self.home)])

    def test_placeholder_config_is_rejected(self) -> None:
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

    def test_malformed_config_reports_error_not_traceback(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config("models: [\n")
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)

    def test_non_mapping_config_root_reports_error_not_traceback(self) -> None:
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

    def test_boolean_iteration_values_rejected(self) -> None:
        # bool is a subclass of int: `max_fix_iterations: true` used to pass
        # the integer check and render as "max_iterations: True".
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_fix_iterations: 5", "max_fix_iterations: true")
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("max_fix_iterations must be an integer", err)

    def test_boolean_shell_timeout_rejected(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace("shell_timeout: 7200", "shell_timeout: true"))
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("shell_timeout must be a positive number", err)

    def test_null_state_dir_rejected(self) -> None:
        # str(None) is "None", which used to pass the regex and point every
        # workflow step at "None/tasks/...".
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace("state_dir: .workflow", "state_dir: null"))
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("workflow.state_dir must be a string", err)

    def test_non_string_adr_dir_rejected(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace("adr_dir: architecture", "adr_dir: 42"))
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("workflow.adr_dir must be a string", err)

    def test_invalid_backend_rejected(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace("backend: opencode", "backend: bogus"))
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("backend must be one of: opencode, cursor", err)

    def test_backend_cursor_requires_both_models(self) -> None:
        # cursor.models.planner.model and cursor.models.executor.model are
        # required (symmetric to opencode's provider/model/reasoning); the
        # opencode section is not required in cursor mode.
        self.assertEqual(self.install(), 0)
        self.write_config(
            "backend: cursor\n"
            "cursor:\n"
            "  models:\n"
            "    planner:\n"
            "      model: composer-2\n"
            "workflow: {}\n"
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("missing required key: cursor.models.executor.model", err)
        self.assertNotIn("opencode", err)

    def test_backend_cursor_placeholder_model_rejected(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(
            "backend: cursor\n"
            "cursor:\n"
            "  models:\n"
            "    planner:\n"
            "      model: <planner-slug>\n"
            "    executor:\n"
            "      model: composer-2\n"
            "workflow: {}\n"
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("placeholder value in cursor.models.planner.model", err)

    def test_backend_cursor_without_cursor_section_rejected(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config("backend: cursor\ncursor: {}\nworkflow: {}\n")
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("missing required key: cursor.models.planner.model", err)
        self.assertIn("missing required key: cursor.models.executor.model", err)

    def test_backend_opencode_requires_opencode_models(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config("backend: opencode\nopencode: {}\nworkflow: {}\n")
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("missing required key: opencode.models.planner.provider", err)

    def test_backend_cursor_without_opencode_section_is_valid(self) -> None:
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
        self.assertEqual(self.install(), 0)

    def test_backend_cursor_with_empty_opencode_section_is_valid(self) -> None:
        # The inactive opencode section is structural only: an empty section
        # renders no agent files, and check_files must not demand them (the
        # render and verify conditions share one completeness predicate).
        self.write_config(
            "backend: cursor\n"
            "opencode: {}\n"
            "cursor:\n"
            "  models:\n"
            "    planner:\n"
            "      model: composer-2\n"
            "    executor:\n"
            "      model: composer-2\n"
            "workflow: {}\n"
        )
        self.assertEqual(self.install(), 0)
        self.assertFalse((self.home / ".config/opencode/agent/planner.md").exists())

    def test_backend_opencode_without_cursor_section_is_valid(self) -> None:
        # Legacy configs (models: folded into opencode.models, no cursor
        # section) stay valid under the default backend.
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
        self.assertEqual(self.install(), 0)

    def test_sound_non_boolean_enabled_rejected(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(
            VALID_BASE
            + "sound:\n"
            "  is_sound_alert_enabled: \"true\"\n"
            '  sound_file: ""\n'
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("sound.is_sound_alert_enabled must be a boolean", err)

    def test_sound_file_non_string_rejected(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(
            VALID_BASE + "sound:\n  is_sound_alert_enabled: true\n  sound_file: [a, b]\n"
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("sound.sound_file must be a string", err)

    def test_sound_missing_absolute_file_rejected(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(
            VALID_BASE
            + "sound:\n  is_sound_alert_enabled: true\n  sound_file: /no/such/dir/x.wav\n"
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", err)

    def test_sound_disabled_allows_missing_file(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(
            VALID_BASE
            + "sound:\n  is_sound_alert_enabled: false\n  sound_file: /no/such/dir/x.wav\n"
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 0, err)

    def test_sound_relative_file_resolved_against_config_dir(self) -> None:
        self.assertEqual(self.install(), 0)
        (self.home / ".config/modus-operandi" / "my.wav").write_bytes(b"RIFF")
        self.write_config(
            VALID_BASE + "sound:\n  is_sound_alert_enabled: true\n  sound_file: my.wav\n"
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 0, err)
