"""Unit tests for the BufferedEmitter live-block drawing (ADR-0011)."""

import io
import pty
import unittest
from collections.abc import Callable
from typing import Any

from tests.env_sandbox import stdout

from .helpers import load_run_pipeline


class BufferedEmitterBlockTest(unittest.TestCase):
    """The live block is redrawn in place without drifting, a shorter block
    erases the leftover rows of a taller one, normal output keeps the block
    visible below it, and fixed lines replace the block as history (no
    stale redraw)."""

    def _emitter(self, mod: Any) -> tuple[Any, Any]:
        gate = mod.GateState()
        emitter = mod.BufferedEmitter(gate)
        return gate, emitter

    def _capture(self, emitter: Any, fn: Callable[[], object]) -> str:
        captured = io.StringIO()
        with stdout(captured):
            fn()
        return captured.getvalue()

    def test_redraw_stays_in_place(self) -> None:
        mod = load_run_pipeline()
        _, emitter = self._emitter(mod)
        out1 = self._capture(emitter, lambda: emitter.emit_live(["a", "b"]))
        # Every drawn row ends with \n: the cursor is left one row BELOW the
        # block, so the next redraw moves up exactly the block height.
        self.assertEqual(out1, "\ra\x1b[K\n\rb\x1b[K\n")
        out2 = self._capture(emitter, lambda: emitter.emit_live(["a", "b"]))
        self.assertEqual(out2, "\x1b[2A\ra\x1b[K\n\rb\x1b[K\n")

    def test_shorter_block_erases_leftover_rows(self) -> None:
        mod = load_run_pipeline()
        _, emitter = self._emitter(mod)
        self._capture(emitter, lambda: emitter.emit_live(["a", "b", "c"]))
        out = self._capture(emitter, lambda: emitter.emit_live(["x"]))
        # Move up 3, rewrite row 1, erase rows 2-3, then move the cursor back
        # up so it sits right below the new 1-row block.
        self.assertEqual(out, "\x1b[3A\rx\x1b[K\n\r\x1b[K\n\r\x1b[K\n\x1b[2A")

    def test_normal_output_keeps_block_visible_below(self) -> None:
        mod = load_run_pipeline()
        _, emitter = self._emitter(mod)
        self._capture(emitter, lambda: emitter.emit_live(["a"]))
        out = self._capture(emitter, lambda: emitter.emit_stdout("echoed"))
        # Clear the block, print the line, redraw the block below it.
        self.assertIn("\x1b[1A\r\x1b[K\n\x1b[1A", out)
        self.assertIn("echoed", out)
        self.assertIn("\ra\x1b[K\n", out)
        # The block content appears exactly once: as the redrawn block.
        self.assertEqual(out.count("\ra\x1b[K\n"), 1)

    def test_fixed_lines_replace_block_no_stale_redraw(self) -> None:
        mod = load_run_pipeline()
        _, emitter = self._emitter(mod)
        self._capture(emitter, lambda: emitter.emit_live(["a"]))
        out = self._capture(
            emitter,
            lambda: (
                emitter.emit_live(["a"], plain=True),
                emitter.emit_live(["step output row"], plain=True),
            ),
        )
        # The fixed rows print plainly in emission order; the step's
        # captured row after them must NOT redraw the stale block under it:
        # the cleared block is not redrawn ("a" prints once, plainly) and
        # the output ends with the step's captured row.
        self.assertIn("step output row", out)
        self.assertEqual(out.count("\ra\x1b[K\n"), 0)
        self.assertEqual(out.count("a\n"), 1)
        self.assertTrue(out.rstrip().endswith("step output row"))

    def test_clear_live_leaves_cursor_at_block_start(self) -> None:
        mod = load_run_pipeline()
        _, emitter = self._emitter(mod)
        self._capture(emitter, lambda: emitter.emit_live(["a", "b"]))
        out = self._capture(emitter, lambda: emitter.clear_live())
        # Move up 2, clear both rows, move back up 2 (cursor at the block
        # start, where the next normal line prints).
        self.assertEqual(out, "\x1b[2A\r\x1b[K\n\r\x1b[K\n\x1b[2A")

    def test_empty_block_is_a_noop(self) -> None:
        mod = load_run_pipeline()
        _, emitter = self._emitter(mod)
        out = self._capture(emitter, lambda: emitter.emit_live([]))
        self.assertEqual(out, "")

    def test_block_lines_are_clamped_to_terminal_width(self) -> None:
        # A line wider than the terminal would wrap onto a second physical
        # row and break the height arithmetic (ghost rows, drifting block):
        # every drawn row is clamped to the terminal width minus one column.
        # The terminal size is read from a real pty whose size is set via
        # TIOCSWINSZ (fd 1 temporarily points at the pty slave).
        mod = load_run_pipeline()
        _, emitter = self._emitter(mod)
        import fcntl
        import os
        import struct
        import sys
        import termios

        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 10, 0, 0))
            assert sys.__stdout__ is not None
            real_out = sys.__stdout__.fileno()
            old_fd = os.dup(real_out)
            os.dup2(slave, real_out)
            try:
                out = self._capture(emitter, lambda: emitter.emit_live(["x" * 50]))
            finally:
                os.dup2(old_fd, real_out)
                os.close(old_fd)
        finally:
            os.close(master)
            os.close(slave)
        # 9 columns = width 10 - 1 margin.
        self.assertEqual(out, "\r" + "x" * 9 + "\x1b[K\n")
