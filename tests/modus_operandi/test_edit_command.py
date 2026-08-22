"""Tests for edit_command._run_edit (the `modus-operandi edit` flow).

The editor is a real script on PATH launched through a real subprocess; the
config is the real package example and apply() re-renders the real artifacts
into a temp layout. Only the environment is controlled (EDITOR, PATH), never
the behavior.
"""

import io
import os
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from modus_operandi import __version__, edit_command, paths
from tests.env_sandbox import env, stderr, stdout

_EXAMPLE = files("modus_operandi").joinpath("data/config.example.yml").read_bytes()


class EditCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.layout = paths.build_paths_from_config_base(self.tmp.name)
        self.config = str(self.layout["config"])
        Path(self.config).parent.mkdir(parents=True, exist_ok=True)
        Path(self.config).write_bytes(_EXAMPLE)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()

    def _write_editor(self, body: str, name: str = "editor") -> Path:
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def _env(self, editor: str | None = "editor", clear: bool = False) -> dict[str, str]:
        overrides = {"PATH": str(self.bin)}
        if editor is not None:
            overrides["EDITOR"] = editor
        if clear:
            return {k: v for k, v in overrides.items()}
        overrides["PATH"] = f"{self.bin}:{os.environ.get('PATH', '')}"
        return overrides

    def test_edit_launches_editor_then_applies(self) -> None:
        # The editor is launched with the config path as its single argument;
        # it changes the config, and on close the config is re-applied for
        # real (marker recorded).
        self._write_editor(
            '#!/bin/sh\nprintf \'%s\' "$1" > "$1.invoked"\n'
            "printf '\\n# edited via test\\n' >> \"$1\"\nexit 0\n"
        )
        with (
            env(self._env()),
            stdout(io.StringIO()) as out,
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 0)
        self.assertEqual(Path(self.config + ".invoked").read_text(encoding="utf-8"), self.config)
        self.assertEqual(self.layout["install_version"].read_text(encoding="utf-8"), __version__)
        self.assertIn("config applied", out.getvalue())

    def test_edit_without_saving_applies_nothing(self) -> None:
        # The editor runs but the file is left byte-identical: the flow
        # reports that nothing changed and does not re-apply.
        self._write_editor("#!/bin/sh\nexit 0\n")
        with (
            env(self._env()),
            stdout(io.StringIO()) as out,
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 0)
        self.assertIn("config unchanged", out.getvalue())
        self.assertNotIn("config applied", out.getvalue())
        self.assertFalse(self.layout["install_version"].exists())

    def test_edit_applies_after_nonzero_editor_exit(self) -> None:
        # A user can save a valid edit and still close the editor non-zero
        # (vim :cq, ...); the config must still be re-applied then.
        self._write_editor(
            "#!/bin/sh\nsed -i 's/backend: opencode/backend: cursor/' \"$1\"\nexit 7\n"
        )
        with (
            env(self._env()),
            stdout(io.StringIO()) as out,
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 0)
        self.assertIn("backend: cursor", Path(self.config).read_text(encoding="utf-8"))
        self.assertIn("config applied", out.getvalue())

    def test_edit_editor_start_failure_returns_nonzero(self) -> None:
        # A script whose interpreter does not exist makes exec fail with
        # OSError: the flow reports it and never applies. The editor is
        # named by its absolute path: execvpe falls through to the next
        # matching binary on PATH when exec of a bare name fails with
        # ENOENT, which on Debian/Ubuntu silently runs /usr/bin/editor.
        editor_path = self._write_editor("#!/nonexistent/interp\n")
        with (
            env(self._env(editor=str(editor_path))),
            stderr(io.StringIO()) as err,
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 1)
        self.assertIn("cannot start editor", err.getvalue())
        self.assertFalse(self.layout["install_version"].exists())

    def test_edit_invalid_config_fails_with_error(self) -> None:
        # apply() re-validates the config: an invalid edit surfaces as an
        # InstallError and aborts `edit` with an error.
        self._write_editor("#!/bin/sh\nprintf 'backend: [unclosed\\n' > \"$1\"\n")
        with (
            env(self._env()),
            stderr(io.StringIO()) as err,
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 1)
        self.assertIn("error: config.yml is invalid, changes not saved", err.getvalue())

    def test_edit_invalid_config_rolls_back_changes(self) -> None:
        # An invalid edit is rolled back: the pre-edit config is restored so
        # the user's broken edit never sticks on disk.
        self._write_editor("#!/bin/sh\nprintf 'backend: [unclosed\\n' > \"$1\"\n")
        with (
            env(self._env()),
            stderr(io.StringIO()),
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 1)
        self.assertEqual(Path(self.config).read_bytes(), _EXAMPLE)

    def test_edit_without_editor_fails_cleanly(self) -> None:
        # An empty PATH and no $VISUAL/$EDITOR: no editor can be resolved and
        # the flow aborts before touching anything.
        with (
            env(self._env(editor="", clear=True)),
            stderr(io.StringIO()) as err,
        ):
            rc = edit_command._run_edit(self.config, self.layout)
        self.assertEqual(rc, 1)
        self.assertIn("no editor found", err.getvalue())
        self.assertFalse(self.layout["install_version"].exists())
