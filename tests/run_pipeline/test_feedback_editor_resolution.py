"""Unit tests for the feedback-editor resolution chain."""

import io
import unittest
from unittest import mock

from .helpers import load_run_pipeline


class FeedbackEditorResolutionTest(unittest.TestCase):
    """The feedback editor resolution chain: $VISUAL -> $EDITOR -> nano ->
    vi, each candidate validated on PATH; None when the whole chain is
    empty (unlike the launcher, which must always return something)."""

    def test_prefers_visual_over_editor(self):
        mod = load_run_pipeline()
        with (
            mock.patch.dict(
                "os.environ", {"VISUAL": "code --wait", "EDITOR": "vim"}, clear=True
            ),
            mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/" + name),
        ):
            self.assertEqual(mod.resolve_editor(), ["code", "--wait"])

    def test_uses_editor_when_visual_unset(self):
        mod = load_run_pipeline()
        with (
            mock.patch.dict("os.environ", {"EDITOR": "emacs -nw"}, clear=True),
            mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/" + name),
        ):
            self.assertEqual(mod.resolve_editor(), ["emacs", "-nw"])

    def test_missing_binary_falls_through_to_next_candidate(self):
        # A VISUAL/EDITOR whose binary is not on PATH is skipped and the
        # chain continues (the launcher would return it as-is instead).
        mod = load_run_pipeline()

        def which(name):
            return "/usr/bin/" + name if name == "vim" else None

        with (
            mock.patch.dict(
                "os.environ", {"VISUAL": "subl", "EDITOR": "vim"}, clear=True
            ),
            mock.patch("shutil.which", side_effect=which),
        ):
            self.assertEqual(mod.resolve_editor(), ["vim"])

    def test_malformed_visual_is_skipped_with_warning(self):
        mod = load_run_pipeline()
        with (
            mock.patch.dict(
                "os.environ", {"VISUAL": 'code --wait"', "EDITOR": "vim"}, clear=True
            ),
            mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/" + name),
            mock.patch("sys.stderr", io.StringIO()) as stderr,
        ):
            self.assertEqual(mod.resolve_editor(), ["vim"])
        self.assertIn("warning", stderr.getvalue())

    def test_falls_back_to_nano_then_vi(self):
        mod = load_run_pipeline()

        def with_nano(name):
            return "/usr/bin/" + name if name in ("nano", "vi") else None

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", side_effect=with_nano),
        ):
            self.assertEqual(mod.resolve_editor(), ["nano"])

        def vi_only(name):
            return "/usr/bin/vi" if name == "vi" else None

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", side_effect=vi_only),
        ):
            self.assertEqual(mod.resolve_editor(), ["vi"])

    def test_no_editor_available_returns_none(self):
        mod = load_run_pipeline()
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value=None),
        ):
            self.assertIsNone(mod.resolve_editor())


class FeedbackEditorPlatformTest(unittest.TestCase):
    """resolve_feedback_editor: the platform chain for the feedback gates
    (ADR-0011) — macOS TextEdit (waited), Linux GUI in a separate window
    (detached), the terminal chain as the no-GUI fallback (waited)."""

    def test_macos_uses_textedit_waited(self):
        mod = load_run_pipeline()
        with mock.patch("sys.platform", "darwin"):
            self.assertEqual(
                mod.resolve_feedback_editor(),
                ("waited", ["open", "-a", "TextEdit", "-W"]),
            )

    def test_linux_flatpak_detached(self):
        # flatpak on PATH and `flatpak info org.gnome.TextEditor` exits 0:
        # the Flatpak GNOME Text Editor is used, detached.
        mod = load_run_pipeline()
        with (
            mock.patch("sys.platform", "linux"),
            mock.patch(
                "shutil.which",
                side_effect=lambda name: "/usr/bin/" + name
                if name == "flatpak"
                else None,
            ),
            mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run,
        ):
            self.assertEqual(
                mod.resolve_feedback_editor(),
                ("detached", ["flatpak", "run", "org.gnome.TextEditor"]),
            )
        self.assertEqual(run.call_args.args[0], ["flatpak", "info", "org.gnome.TextEditor"])

    def test_linux_flatpak_not_installed_falls_to_gnome_text_editor(self):
        # flatpak on PATH but the app not installed (exit 1): the RPM binary
        # is tried next.
        mod = load_run_pipeline()

        def which(name):
            return "/usr/bin/" + name if name in ("flatpak", "gnome-text-editor") else None

        with (
            mock.patch("sys.platform", "linux"),
            mock.patch("shutil.which", side_effect=which),
            mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
        ):
            self.assertEqual(
                mod.resolve_feedback_editor(), ("detached", ["gnome-text-editor"])
            )

    def test_linux_gio_open_detached(self):
        mod = load_run_pipeline()

        def which(name):
            return "/usr/bin/" + name if name == "gio" else None

        with (
            mock.patch("sys.platform", "linux"),
            mock.patch("shutil.which", side_effect=which),
            mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
        ):
            self.assertEqual(mod.resolve_feedback_editor(), ("detached", ["gio", "open"]))

    def test_linux_xdg_open_detached(self):
        mod = load_run_pipeline()

        def which(name):
            return "/usr/bin/" + name if name == "xdg-open" else None

        with (
            mock.patch("sys.platform", "linux"),
            mock.patch("shutil.which", side_effect=which),
            mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
        ):
            self.assertEqual(
                mod.resolve_feedback_editor(), ("detached", ["xdg-open"])
            )

    def test_linux_no_gui_falls_back_to_terminal_chain(self):
        mod = load_run_pipeline()

        def which(name):
            return "/usr/bin/" + name if name in ("nano", "vi") else None

        with (
            mock.patch("sys.platform", "linux"),
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", side_effect=which),
            mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
        ):
            self.assertEqual(mod.resolve_feedback_editor(), ("waited", ["nano"]))

    def test_no_editor_returns_none(self):
        mod = load_run_pipeline()
        with (
            mock.patch("sys.platform", "linux"),
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value=None),
            mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
        ):
            self.assertIsNone(mod.resolve_feedback_editor())
