"""Tests for open_feedback_editor against real ptys and real editor scripts.

open_feedback_editor owns the feedback gates: on a TTY it opens the
platform editor (ADR-0011) — the "waited" path (the terminal chain) runs
blocking and answers `continue` on close; the macOS TextEdit and Linux GUI
paths are "detached" (separate window, the gate stays interactive). The
tests run a
real pty pair (sys.stdin/sys.stdout are the real pty slave), real editor
executables on PATH and real subprocesses; only the macOS branches cannot
"""

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

from tests.env_sandbox import cwd, env, stderr, stdin, stdout

from .helpers import load_run_pipeline


def _write_script(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


class FeedbackEditorTest(unittest.TestCase):
    """The platform resolution (editor.py) runs against real binaries on
    PATH; the gate answer is observed on a real pty pair."""

    def _bins(self, tmp: str) -> Path:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir(exist_ok=True)
        return bin_dir

    def _path_env(self, bin_dir: Path) -> str:
        return f"{bin_dir}:{os.environ.get('PATH', '')}"

    def _feedback_path(self, tmp: str) -> Path:
        return Path(tmp) / ".workflow" / "tasks" / "current" / "feedback.md"

    @contextmanager
    def _tty(self, is_tty: bool = True) -> Iterator[tuple[int, int]]:
        """A real pty pair: sys.stdin/sys.stdout are the slave end (isatty
        True), or plain StringIO streams (isatty False). Yields
        (master_fd, slave_fd)."""
        master, slave = pty.openpty()
        try:
            slave_in: Any
            slave_out: Any
            if is_tty:
                slave_in = os.fdopen(slave, "r", encoding="utf-8")
                slave_out = os.fdopen(slave, "w", encoding="utf-8")
            else:
                slave_in = io.StringIO()
                slave_out = io.StringIO()
            with stdin(slave_in), stdout(slave_out):
                yield master, slave
        finally:
            os.close(master)
            if is_tty:
                os.close(slave)

    def test_answers_continue_after_terminal_editor(self) -> None:
        # Linux without a GUI: the terminal chain runs blocking and the
        # wrapper answers the gate with `continue`. nano is a real script on
        # PATH; the gate answer is observed on the real pty.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self._bins(tmp)
            _write_script(bin_dir / "nano", "#!/bin/sh\nexit 0\n")
            _write_script(bin_dir / "flatpak", "#!/bin/sh\nexit 1\n")
            path = self._feedback_path(tmp)
            with self._tty() as (master, slave), cwd(tmp), env({"PATH": str(bin_dir)}, clear=True):
                result = mod.open_feedback_editor(
                    ".workflow", threading.Event(), master, "adr-feedback-gate"
                )
                answer = os.read(slave, 64)
            self.assertTrue(result)
            self.assertEqual(answer, b"continue\n")
            self.assertTrue(path.is_file())

    def test_linux_gui_detached_leaves_gate_interactive(self) -> None:
        # The Linux GUI path launches the editor in a separate window and
        # NEVER answers the gate: the user presses continue after closing
        # the window. Forwarding is never paused. flatpak answers the probe
        # with 0, so the detached branch runs with a real Popen.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self._bins(tmp)
            _write_script(bin_dir / "flatpak", "#!/bin/sh\nexit 0\n")
            pause = threading.Event()
            with (
                self._tty(),
                cwd(tmp),
                env({"PATH": str(bin_dir)}, clear=True),
            ):
                result = mod.open_feedback_editor(".workflow", pause, -1, "adr-gate:1")
            self.assertFalse(result)
            self.assertFalse(pause.is_set())

    def test_falls_back_when_not_a_tty(self) -> None:
        # Plain streams (isatty False): the file is still created and the
        # gate stays interactive — no editor is launched.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self._bins(tmp)
            _write_script(bin_dir / "nano", '#!/bin/sh\nmkdir -p "$1.ran"\n')
            path = self._feedback_path(tmp)
            with (
                self._tty(is_tty=False),
                cwd(tmp),
                env({"PATH": str(bin_dir)}, clear=True),
            ):
                result = mod.open_feedback_editor(
                    ".workflow", threading.Event(), -1, "adr-feedback-gate"
                )
            self.assertFalse(result)
            self.assertTrue(path.is_file())
            self.assertFalse(Path(str(path) + ".ran").exists())

    def test_falls_back_when_no_editor(self) -> None:
        # No editor binary anywhere on PATH: the flow falls back with the
        # file still created.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self._bins(tmp)
            path = self._feedback_path(tmp)
            with (
                self._tty(),
                cwd(tmp),
                env({"PATH": str(bin_dir)}, clear=True),
            ):
                result = mod.open_feedback_editor(
                    ".workflow", threading.Event(), -1, "adr-feedback-gate"
                )
            self.assertFalse(result)
            self.assertTrue(path.is_file())

    def test_fallback_never_leaves_forwarding_paused(self) -> None:
        # In the fallback the user answers the gate manually, so stdin
        # forwarding must never be left paused.
        mod = load_run_pipeline()
        pause = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self._bins(tmp)
            with (
                self._tty(is_tty=False),
                cwd(tmp),
                env({"PATH": str(bin_dir)}, clear=True),
            ):
                result = mod.open_feedback_editor(".workflow", pause, -1, None)
            self.assertFalse(result)
            self.assertFalse(pause.is_set())
            self.assertTrue(self._feedback_path(tmp).is_file())

    def test_detached_launch_failure_falls_back(self) -> None:
        # The Linux GUI branch with a broken editor script: the real Popen
        # raises OSError and the flow falls back (no crash, no pause).
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self._bins(tmp)
            _write_script(bin_dir / "gnome-text-editor", "#!/nonexistent/interp\n")
            pause = threading.Event()
            with (
                self._tty(),
                cwd(tmp),
                env({"PATH": str(bin_dir)}, clear=True),
                stderr(io.StringIO()) as err,
            ):
                result = mod.open_feedback_editor(".workflow", pause, -1, "adr-feedback-gate")
            self.assertFalse(result)
            self.assertFalse(pause.is_set())
            self.assertIn("cannot start editor", err.getvalue())
