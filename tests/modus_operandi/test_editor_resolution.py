"""Unit tests for the launcher's editor resolution."""

import io
import tempfile
import unittest
from unittest import mock

from .helpers import load_modus_operandi


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

    def _on_path(self, name: str) -> str:
        return "/usr/bin/" + name

    def test_editor_prefers_visual_over_editor(self) -> None:
        with (
            mock.patch.dict(
                "os.environ",
                {"VISUAL": "code --wait", "EDITOR": "vim"},
                clear=True,
            ),
            mock.patch("shutil.which", side_effect=self._on_path),
        ):
            self.assertEqual(self.mod.resolve_editor(), ["code", "--wait"])

    def test_editor_uses_editor_when_visual_unset(self) -> None:
        with (
            mock.patch.dict("os.environ", {"EDITOR": "emacs -nw"}, clear=True),
            mock.patch("shutil.which", side_effect=self._on_path),
        ):
            self.assertEqual(self.mod.resolve_editor(), ["emacs", "-nw"])

    def test_editor_falls_back_to_nano_then_vi(self) -> None:
        # nano wins over vi when both are on PATH.
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", side_effect=self._on_path),
        ):
            self.assertEqual(self.mod.resolve_editor(), ["nano"])

        # vi is used only when nano is missing.
        def which_vi_only(name: str) -> str | None:
            return self._on_path(name) if name == "vi" else None

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", side_effect=which_vi_only),
        ):
            self.assertEqual(self.mod.resolve_editor(), ["vi"])

    def test_editor_stale_visual_falls_back_to_a_working_editor(self) -> None:
        # Regression: a $VISUAL/$EDITOR pointing at a removed binary (e.g.
        # `code --wait` after code was uninstalled) must not be returned
        # unvalidated — the chain falls through to a working editor.
        def which(name: str) -> str | None:
            return "/usr/bin/nano" if name == "nano" else None

        with (
            mock.patch.dict("os.environ", {"VISUAL": "code --wait", "EDITOR": "vim"}, clear=True),
            mock.patch("shutil.which", side_effect=which),
        ):
            self.assertEqual(self.mod.resolve_editor(), ["nano"])

    def test_editor_no_editor_returns_none(self) -> None:
        # A fully empty chain (no $VISUAL/$EDITOR binary and no nano/vi)
        # signals "no editor" instead of returning a missing binary.
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value=None),
        ):
            self.assertIsNone(self.mod.resolve_editor())

    def test_editor_malformed_visual_falls_back_to_editor(self) -> None:
        with (
            mock.patch.dict("os.environ", {"VISUAL": 'code --wait"', "EDITOR": "vim"}, clear=True),
            mock.patch("shutil.which", side_effect=self._on_path),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            self.assertEqual(self.mod.resolve_editor(), ["vim"])
        self.assertIn("malformed", err.getvalue())

    def test_editor_malformed_value_falls_back_to_default(self) -> None:
        # An unbalanced quote makes shlex.split raise ValueError; the value is
        # skipped (with a warning) instead of crashing with a traceback.
        with (
            mock.patch.dict("os.environ", {"EDITOR": "emacs '"}, clear=True),
            mock.patch("shutil.which", return_value="/usr/bin/nano"),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            self.assertEqual(self.mod.resolve_editor(), ["nano"])
        self.assertIn("malformed", err.getvalue())
