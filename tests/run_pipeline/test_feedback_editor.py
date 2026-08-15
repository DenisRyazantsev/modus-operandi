"""Unit tests for open_feedback_editor."""

import io
import os
import pty
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


class FeedbackEditorTest(unittest.TestCase):
    """open_feedback_editor owns the revise gate: on a TTY with a usable
    editor it runs the editor and answers `continue`; otherwise it falls
    back (file created, gate stays interactive, forwarding never paused)."""

    @contextmanager
    def _tty(self, is_tty=True):
        with (
            mock.patch("sys.stdin.isatty", return_value=is_tty),
            mock.patch("sys.stdout.isatty", return_value=is_tty),
        ):
            yield

    def test_answers_continue_after_editor(self):
        mod = load_run_pipeline()
        real_master, real_slave = pty.openpty()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "feedback.md"
                written = []
                with (
                    self._tty(),
                    mock.patch.dict("os.environ", {}, clear=True),
                    mock.patch("shutil.which", return_value="/usr/bin/nano"),
                    mock.patch(
                        "subprocess.run", return_value=mock.Mock(returncode=0)
                    ) as run,
                    mock.patch(
                        "os.write",
                        side_effect=lambda fd, data: written.append((fd, data))
                        or len(data),
                    ),
                ):
                    result = mod.open_feedback_editor(
                        path, threading.Event(), real_master
                    )
                self.assertTrue(result)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0], ["nano", str(path)])
                self.assertEqual(written, [(real_master, b"continue\n")])
        finally:
            os.close(real_master)
            os.close(real_slave)

    def test_falls_back_when_not_a_tty(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            with (
                self._tty(is_tty=False),
                mock.patch("subprocess.run") as run,
                mock.patch("os.write") as write,
            ):
                result = mod.open_feedback_editor(path, threading.Event(), 999)
            self.assertFalse(result)
            run.assert_not_called()
            write.assert_not_called()
            # The file is still created (the fallback keeps manual input).
            self.assertTrue(path.is_file())

    def test_falls_back_when_no_editor(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            with (
                self._tty(),
                mock.patch("shutil.which", return_value=None),
                mock.patch("subprocess.run") as run,
            ):
                result = mod.open_feedback_editor(path, threading.Event(), 999)
            self.assertFalse(result)
            run.assert_not_called()
            self.assertTrue(path.is_file())

    def test_fallback_never_leaves_forwarding_paused(self):
        # In the fallback the user answers the gate manually, so stdin
        # forwarding must never be left paused.
        mod = load_run_pipeline()
        pause = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            with self._tty(is_tty=False):
                result = mod.open_feedback_editor(path, pause, 999)
            self.assertFalse(result)
            self.assertFalse(pause.is_set())

    def test_editor_failure_falls_back(self):
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            with (
                self._tty(),
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch("shutil.which", return_value="/usr/bin/nano"),
                mock.patch("subprocess.run", side_effect=OSError("boom")),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                result = mod.open_feedback_editor(path, threading.Event(), 999)
            self.assertFalse(result)
