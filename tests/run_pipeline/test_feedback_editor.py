"""Unit tests for open_feedback_editor."""

import io
import os
import pty
import tempfile
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from .helpers import load_run_pipeline


def _write(written: list[tuple[int, bytes]]) -> Any:
    def _impl(fd: int, data: bytes) -> int:
        written.append((fd, data))
        return len(data)

    return _impl


class FeedbackEditorTest(unittest.TestCase):
    """open_feedback_editor owns the feedback gates: on a TTY it opens the
    platform editor (ADR-0011) — "waited" paths (macOS TextEdit, the
    terminal chain) run blocking and answer `continue` on close; the Linux
    GUI path is "detached" (separate window, the gate stays interactive).
    Without a TTY or an editor it falls back (file created, gate stays
    interactive, forwarding never paused)."""

    @contextmanager
    def _tty(self, is_tty: bool = True) -> Iterator[None]:
        with (
            mock.patch("sys.stdin.isatty", return_value=is_tty),
            mock.patch("sys.stdout.isatty", return_value=is_tty),
        ):
            yield

    def _feedback_path(self, tmp: str) -> Path:
        return Path(tmp) / ".workflow" / "tasks" / "current" / "feedback.md"

    def test_answers_continue_after_terminal_editor(self) -> None:
        # Linux without a GUI: the terminal chain runs blocking and the
        # wrapper answers the gate with `continue`.
        mod = load_run_pipeline()
        real_master, real_slave = pty.openpty()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = self._feedback_path(tmp)
                written: list[tuple[int, bytes]] = []

                def which(name: str) -> str | None:
                    return "/usr/bin/" + name if name in ("nano", "vi") else None

                with (
                    self._tty(),
                    mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                    mock.patch("sys.platform", "linux"),
                    mock.patch.dict("os.environ", {}, clear=True),
                    mock.patch("shutil.which", side_effect=which),
                    # The flatpak probe (resolve_feedback_editor) and the
                    # editor run both go through subprocess.run; returncode
                    # 1 for the probe means "not installed".
                    mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)) as run,
                    mock.patch("os.write", side_effect=_write(written)),
                ):
                    result = mod.open_feedback_editor(
                        ".workflow", threading.Event(), real_master, "adr-feedback-gate"
                    )
                self.assertTrue(result)
                self.assertEqual(run.call_args.args[0], ["nano", str(path)])
                self.assertEqual(written, [(real_master, b"continue\n")])
        finally:
            os.close(real_master)
            os.close(real_slave)

    def test_macos_textedit_waited_answers_continue(self) -> None:
        mod = load_run_pipeline()
        real_master, real_slave = pty.openpty()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = self._feedback_path(tmp)
                written: list[tuple[int, bytes]] = []
                with (
                    self._tty(),
                    mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                    mock.patch("sys.platform", "darwin"),
                    mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run,
                    mock.patch("os.write", side_effect=_write(written)),
                ):
                    result = mod.open_feedback_editor(
                        ".workflow", threading.Event(), real_master, "adr-feedback-gate"
                    )
                self.assertTrue(result)
                self.assertEqual(
                    run.call_args.args[0],
                    ["open", "-a", "TextEdit", "-W", str(path)],
                )
                self.assertEqual(written, [(real_master, b"continue\n")])
        finally:
            os.close(real_master)
            os.close(real_slave)

    def test_linux_gui_detached_leaves_gate_interactive(self) -> None:
        # The Linux GUI path launches the editor in a separate window and
        # NEVER answers the gate: the user presses continue after closing
        # the window. Forwarding is never paused.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._feedback_path(tmp)
            pause = threading.Event()
            with (
                self._tty(),
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("sys.platform", "linux"),
                mock.patch(
                    "shutil.which",
                    side_effect=lambda name: "/usr/bin/" + name if name == "flatpak" else None,
                ),
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)),
                mock.patch("subprocess.Popen") as popen,
                mock.patch("os.write") as write,
            ):
                result = mod.open_feedback_editor(".workflow", pause, 999, "adr-gate:1")
            self.assertFalse(result)
            self.assertFalse(pause.is_set())
            popen.assert_called_once()
            self.assertEqual(
                popen.call_args.args[0],
                ["flatpak", "run", "org.gnome.TextEditor", str(path)],
            )
            write.assert_not_called()

    def test_falls_back_when_not_a_tty(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._feedback_path(tmp)
            with (
                self._tty(is_tty=False),
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("subprocess.run") as run,
                mock.patch("subprocess.Popen") as popen,
                mock.patch("os.write") as write,
            ):
                result = mod.open_feedback_editor(
                    ".workflow", threading.Event(), 999, "adr-feedback-gate"
                )
            self.assertFalse(result)
            run.assert_not_called()
            popen.assert_not_called()
            write.assert_not_called()
            # The file is still created (the fallback keeps manual input).
            self.assertTrue(path.is_file())

    def test_falls_back_when_no_editor(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._feedback_path(tmp)
            with (
                self._tty(),
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("sys.platform", "linux"),
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch("shutil.which", return_value=None),
                mock.patch("subprocess.run") as run,
            ):
                result = mod.open_feedback_editor(
                    ".workflow", threading.Event(), 999, "adr-feedback-gate"
                )
            self.assertFalse(result)
            run.assert_not_called()
            self.assertTrue(path.is_file())

    def test_fallback_never_leaves_forwarding_paused(self) -> None:
        # In the fallback the user answers the gate manually, so stdin
        # forwarding must never be left paused.
        mod = load_run_pipeline()
        pause = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._feedback_path(tmp)
            with (
                self._tty(is_tty=False),
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
            ):
                result = mod.open_feedback_editor(".workflow", pause, 999, None)
            self.assertFalse(result)
            self.assertFalse(pause.is_set())
            self.assertTrue(path.is_file())

    def test_waited_editor_failure_falls_back(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            with (
                self._tty(),
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("sys.platform", "darwin"),
                mock.patch("subprocess.run", side_effect=OSError("boom")),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                result = mod.open_feedback_editor(
                    ".workflow", threading.Event(), 999, "adr-feedback-gate"
                )
            self.assertFalse(result)

    def test_detached_launch_failure_falls_back(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            with (
                self._tty(),
                mock.patch.object(Path, "cwd", return_value=Path(tmp)),
                mock.patch("sys.platform", "linux"),
                mock.patch(
                    "shutil.which",
                    side_effect=lambda name: (
                        "/usr/bin/" + name if name == "gnome-text-editor" else None
                    ),
                ),
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)),
                mock.patch("subprocess.Popen", side_effect=OSError("boom")),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                result = mod.open_feedback_editor(
                    ".workflow", threading.Event(), 999, "adr-feedback-gate"
                )
            self.assertFalse(result)
