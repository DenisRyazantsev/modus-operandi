"""Tests for the launcher's editor resolution against real PATH binaries.

The resolution chain is $VISUAL -> $EDITOR -> nano -> vi, each candidate
validated on PATH. The tests build a real bin/ directory with real
executable files and control PATH, so shutil.which performs a genuine
lookup instead of a stub.
"""

import importlib.util
import io
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.env_sandbox import env, stderr

from .helpers import load_modus_operandi

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_EDITOR_SRC = REPO_ROOT / "src" / "modus_operandi" / "editor.py"


def _load_editor() -> types.ModuleType:
    """The launcher's editor.py as a module (resolve_feedback_editor is not
    re-exported by cli.py, so it is loaded from source directly)."""
    spec = importlib.util.spec_from_file_location("editor_under_test", _EDITOR_SRC)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EditorResolutionTest(unittest.TestCase):
    """The launcher's editor resolution chain: $VISUAL -> $EDITOR -> nano ->
    vi, each candidate validated on PATH, with malformed values skipped. The
    chain itself lives in the shared editor.py, re-exported by the launcher
    (and used by the run-pipeline wrapper's feedback gate too)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_modus_operandi(self.xdg)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()

    def _make(self, *names: str) -> None:
        for name in names:
            (self.bin / name).write_text("#!/bin/sh\nexit 0\n")
            (self.bin / name).chmod(0o755)

    def _path(self) -> str:
        # PATH limited to the temp bin/: a real lookup that is deterministic
        # regardless of which editors the host machine has installed.
        return str(self.bin)

    def test_editor_prefers_visual_over_editor(self) -> None:
        self._make("code", "vim")
        with env({"VISUAL": "code --wait", "EDITOR": "vim", "PATH": self._path()}, clear=True):
            self.assertEqual(self.mod.resolve_editor(), ["code", "--wait"])

    def test_editor_uses_editor_when_visual_unset(self) -> None:
        self._make("emacs", "vim")
        with env({"EDITOR": "emacs -nw", "PATH": self._path()}, clear=True):
            self.assertEqual(self.mod.resolve_editor(), ["emacs", "-nw"])

    def test_editor_falls_back_to_nano_then_vi(self) -> None:
        # nano wins over vi when both are on PATH.
        self._make("nano", "vi")
        with env({"PATH": self._path()}, clear=True):
            self.assertEqual(self.mod.resolve_editor(), ["nano"])

        # vi is used only when nano is missing.
        self.bin.joinpath("nano").unlink()
        with env({"PATH": self._path()}, clear=True):
            self.assertEqual(self.mod.resolve_editor(), ["vi"])

    def test_editor_stale_visual_falls_back_to_a_working_editor(self) -> None:
        # Regression: a $VISUAL/$EDITOR pointing at a removed binary (e.g.
        # `code --wait` after code was uninstalled) must not be returned
        # unvalidated — the chain falls through to a working editor.
        self._make("nano")
        with env({"VISUAL": "code --wait", "EDITOR": "vim", "PATH": self._path()}, clear=True):
            self.assertEqual(self.mod.resolve_editor(), ["nano"])

    def test_editor_no_editor_returns_none(self) -> None:
        # A fully empty chain (no $VISUAL/$EDITOR binary and no nano/vi)
        # signals "no editor" instead of returning a missing binary.
        with env({"PATH": self._path()}, clear=True):
            self.assertIsNone(self.mod.resolve_editor())

    def test_editor_malformed_visual_falls_back_to_editor(self) -> None:
        self._make("vim")
        err = io.StringIO()
        with (
            env({"VISUAL": 'code --wait"', "EDITOR": "vim", "PATH": self._path()}, clear=True),
            stderr(err),
        ):
            self.assertEqual(self.mod.resolve_editor(), ["vim"])
        self.assertIn("malformed", err.getvalue())

    def test_editor_malformed_value_falls_back_to_default(self) -> None:
        # An unbalanced quote makes shlex.split raise ValueError; the value is
        # skipped (with a warning) instead of crashing with a traceback.
        self._make("nano")
        err = io.StringIO()
        with (
            env({"EDITOR": "emacs '", "PATH": self._path()}, clear=True),
            stderr(err),
        ):
            self.assertEqual(self.mod.resolve_editor(), ["nano"])
        self.assertIn("malformed", err.getvalue())


class FeedbackEditorResolutionTest(unittest.TestCase):
    """resolve_feedback_editor: the platform editor for the feedback gates.

    macOS TextEdit and the Linux GUI are "detached" (separate window, the
    gate stays interactive — the user answers `continue` in the terminal);
    the no-GUI fallback is the "waited" terminal chain (the wrapper answers
    the gate on editor close)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.editor = _load_editor()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()

    def _make(self, *names: str) -> None:
        for name in names:
            (self.bin / name).write_text("#!/bin/sh\nexit 0\n")
            (self.bin / name).chmod(0o755)

    def test_macos_textedit_is_detached_without_wait(self) -> None:
        # Regression: `open -a TextEdit -W` waited for the whole TextEdit app
        # to QUIT (closing the document window is not enough, and an
        # already-running instance made it block until THAT instance exited),
        # hanging the run at the feedback gate with the menu never drawn.
        # The macOS branch must be detached like the Linux GUI one: the gate
        # stays interactive and the user presses continue in the terminal.
        with mock.patch("sys.platform", "darwin"):
            self.assertEqual(
                self.editor.resolve_feedback_editor(),
                ("detached", ["open", "-a", "TextEdit"]),
            )

    def test_linux_gui_is_detached(self) -> None:
        # flatpak wins when it reports the GNOME Text Editor installed...
        self._make("flatpak", "gnome-text-editor")
        with mock.patch("sys.platform", "linux"), env({"PATH": str(self.bin)}, clear=True):
            self.assertEqual(
                self.editor.resolve_feedback_editor(),
                ("detached", ["flatpak", "run", "org.gnome.TextEditor"]),
            )
            # The generic binary wins when the probe fails.
            self.bin.joinpath("flatpak").write_text("#!/bin/sh\nexit 1\n")
            mode, cmd = self.editor.resolve_feedback_editor()
        self.assertEqual(mode, "detached")
        self.assertIn("gnome-text-editor", cmd)

    def test_no_gui_falls_back_to_waited_terminal_chain(self) -> None:
        # No GUI launcher on PATH: the terminal chain (nano here) is the
        # waited editor — the wrapper answers the gate on editor close.
        self._make("nano")
        with mock.patch("sys.platform", "linux"), env({"PATH": str(self.bin)}, clear=True):
            self.assertEqual(self.editor.resolve_feedback_editor(), ("waited", ["nano"]))

    def test_no_editor_at_all_returns_none(self) -> None:
        with mock.patch("sys.platform", "linux"), env({"PATH": str(self.bin)}, clear=True):
            self.assertIsNone(self.editor.resolve_feedback_editor())


class EditorCopiesTest(unittest.TestCase):
    """The repo ships two byte-identical copies of editor.py on purpose: the
    launcher's copy (this package) and the rendered copy under
    data/pipeline_scripts/ used by the installed run-pipeline wrapper. The
    resolution chain itself is tested once (above); the only thing that can
    go wrong with the copy is drift, which this test pins."""

    def test_editor_pipeline_copy_is_identical_to_launcher_copy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        launcher = root / "src" / "modus_operandi" / "editor.py"
        pipeline = root / "src" / "modus_operandi" / "data" / "pipeline_scripts" / "editor.py"
        self.assertEqual(
            pipeline.read_bytes(),
            launcher.read_bytes(),
            "data/pipeline_scripts/editor.py drifted from modus_operandi/editor.py",
        )
