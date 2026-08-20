"""Unit tests for edit_command._run_edit (the `spec-run edit` flow)."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spec_run import InstallError, edit_command, installer, paths


class EditCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.layout = paths.build_paths_from_config_base(self.tmp.name)
        self.config = str(self.layout["config"])
        Path(self.config).parent.mkdir(parents=True, exist_ok=True)
        Path(self.config).write_text("backend: opencode\n", encoding="utf-8")

    def _patch_editor_chain(self, editor="/usr/bin/nano"):
        return (
            mock.patch.object(edit_command, "resolve_editor", return_value=[editor]),
            mock.patch.object(edit_command.subprocess, "run"),
            mock.patch.object(installer, "apply", return_value=(False, {})),
        )

    def test_edit_launches_editor_then_applies(self):
        calls: list[list[str]] = []

        def fake_run(cmd, check=True):
            calls.append(cmd)
            return mock.Mock(returncode=0)

        with (
            mock.patch.object(edit_command, "resolve_editor", return_value=["nano"]),
            mock.patch.object(edit_command.subprocess, "run", side_effect=fake_run),
            mock.patch.object(installer, "apply", return_value=(False, {})) as apply,
            mock.patch("sys.stdout", mock.Mock()),
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["nano", self.config]])
        apply.assert_called_once_with(self.layout)

    def test_edit_applies_after_nonzero_editor_exit(self):
        # A user can save a valid edit and still close the editor non-zero
        # (vim :cq, ...); the config must still be re-applied then.
        with (
            mock.patch.object(edit_command, "resolve_editor", return_value=["nano"]),
            mock.patch.object(
                edit_command.subprocess, "run", return_value=mock.Mock(returncode=7)
            ),
            mock.patch.object(installer, "apply", return_value=(False, {})) as apply,
            mock.patch("sys.stdout", mock.Mock()),
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 0)
        apply.assert_called_once_with(self.layout)

    def test_edit_editor_start_failure_returns_nonzero(self):
        def fake_run(cmd, check=True):
            raise OSError("no such file")

        with (
            mock.patch.object(edit_command, "resolve_editor", return_value=["nano"]),
            mock.patch.object(edit_command.subprocess, "run", side_effect=fake_run),
            mock.patch.object(installer, "apply") as apply,
            mock.patch("sys.stderr", mock.Mock()),
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 1)
        apply.assert_not_called()

    def test_edit_invalid_config_fails_with_error(self):
        # apply() re-validates the config: an invalid edit surfaces as an
        # InstallError and aborts `edit` with an error.
        with (
            mock.patch.object(edit_command, "resolve_editor", return_value=["nano"]),
            mock.patch.object(
                edit_command.subprocess, "run", return_value=mock.Mock(returncode=0)
            ),
            mock.patch.object(
                installer, "apply", side_effect=InstallError("invalid config.yml")
            ),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 1)
        self.assertIn("error: config.yml is invalid, changes not saved", err.getvalue())

    def test_edit_invalid_config_rolls_back_changes(self):
        # An invalid edit is rolled back: the pre-edit config is restored so
        # the user's broken edit never sticks on disk.
        original = Path(self.config).read_bytes()

        def fake_run(cmd, check=True):
            Path(self.config).write_text("backend: bogus\n", encoding="utf-8")
            return mock.Mock(returncode=0)

        with (
            mock.patch.object(edit_command, "resolve_editor", return_value=["nano"]),
            mock.patch.object(edit_command.subprocess, "run", side_effect=fake_run),
            mock.patch.object(
                installer, "apply", side_effect=InstallError("invalid config.yml")
            ),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 1)
        self.assertEqual(Path(self.config).read_bytes(), original)

    def test_edit_without_editor_fails_cleanly(self):
        with (
            mock.patch.object(edit_command, "resolve_editor", return_value=None),
            mock.patch.object(edit_command.subprocess, "run") as run,
            mock.patch.object(installer, "apply") as apply,
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 1)
        run.assert_not_called()
        apply.assert_not_called()
        self.assertIn("editor", err.getvalue())
