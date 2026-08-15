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
