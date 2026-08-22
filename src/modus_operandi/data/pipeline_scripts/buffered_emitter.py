"""BufferedEmitter: the gate-open output buffering policy for live events.

One responsibility: own the wrapper's console output and the gate-open
buffering policy for it. While a human-gate menu is on screen (GateState
raised by the stdout reader), finished steps and live-block lines are
appended to the buffer instead of printed; flush() prints them — the
fixed history lines, then the step markers — and is called when the
engine moves past the gate or the wrapper stops.

The emitter is also the single owner of the live status block (ADR-0011):
every normal line clears the drawn block first (so history output never
clobbers it) and redraws it afterwards, keeping the block at the bottom of
the terminal. A lock serializes the two writer threads (the monitor thread
and the main thread echoing specify's stdout).
"""

from __future__ import annotations

import shutil
import sys
import threading
from typing import Any

from display import print_step_result
from gate_state import GateState


class BufferedEmitter:
    """Owns the gate-open output buffering policy and the live block drawing."""

    def __init__(self, gate: GateState) -> None:
        self._gate = gate
        self._lock = threading.Lock()
        self._buffered_steps: list[tuple[str, dict[str, Any], int | None, int | None]] = []
        self._buffered_fixed: list[str] = []
        self._buffered_block: list[str] | None = None
        self._block_height = 0
        self._last_block: list[str] = []

    def emit_stdout(self, line: str) -> None:
        """Echo one of specify's own stdout lines (the main thread).

        While the gate menu is on screen the drawn block stays cleared (the
        menu must be readable); otherwise the block is redrawn after the
        line so it remains at the bottom of the terminal.
        """
        with self._lock:
            self._clear_block()
            print(line, flush=True)
            if not self._gate.is_open:
                self._redraw_block()

    def emit_step(
        self,
        step_id: str,
        result: dict[str, Any],
        step_index: int | None = None,
        total_steps: int | None = None,
    ) -> None:
        """Buffer or print one finished step result, per the gate state."""
        with self._lock:
            if self._gate.is_open:
                self._buffered_steps.append((step_id, result, step_index, total_steps))
            else:
                self._clear_block()
                print_step_result(step_id, result, step_index, total_steps)
                self._redraw_block()

    def emit_live(self, lines: list[str], plain: bool = False) -> None:
        """Buffer or print live-block lines, per the gate state.

        `plain` lines are printed plainly with `\n` and nothing is redrawn
        after them: the fixed history lines (the block's last state) and the
        non-TTY per-event lines both take this path. The other lines are the
        live block (drawn in place with ANSI).
        """
        if not lines:
            return
        with self._lock:
            if self._gate.is_open:
                if plain:
                    self._buffered_fixed.extend(lines)
                else:
                    self._buffered_block = lines
            elif plain:
                self._clear_block()
                for line in lines:
                    print(line, flush=True)
                # The fixed lines replaced the block as history: forget the
                # old copy, so the following step marker does not redraw a
                # stale live block under it.
                self._last_block = []
            else:
                self._draw_block(lines)

    def clear_live(self) -> None:
        """Clear the drawn live block (e.g. before the run statistics)."""
        with self._lock:
            self._clear_block()

    def flush(self) -> None:
        """Print the events that were buffered while the gate menu was open.

        The fixed history lines print first, then the step markers, so the
        "agent lines precede the step's completion marker" invariant holds
        for buffered output too; the latest live block is drawn last, right
        before live printing resumes — nothing is lost.
        """
        with self._lock:
            self._clear_block()
            for line in self._buffered_fixed:
                print(line, flush=True)
            self._buffered_fixed.clear()
            for step_id, result, step_index, total_steps in self._buffered_steps:
                print_step_result(step_id, result, step_index, total_steps)
            self._buffered_steps.clear()
            if self._buffered_block is not None:
                self._draw_block(self._buffered_block)
                self._buffered_block = None

    def _draw_block(self, lines: list[str]) -> None:
        """Draw the live block in place (ANSI), overwriting the old one.

        Every drawn row ends with a newline, so the cursor is left at the
        start of the row BELOW the block: redrawing then moves up `old`
        rows to reach the block start exactly, and the block never drifts.
        A shorter new block must still erase the leftover rows of the
        previously drawn taller block — the empty lines are the erasure,
        and after them the cursor is moved back up so it stays right below
        the new block. Every row is clamped to the terminal width (minus
        one column of margin): a wrapped row would occupy TWO physical
        lines, silently breaking the height arithmetic and leaving ghost
        rows on screen.
        """
        if not lines:
            return
        width = max(1, shutil.get_terminal_size().columns - 1)
        n = len(lines)
        old = self._block_height
        if old:
            sys.stdout.write(f"\x1b[{old}A")
        for i in range(max(n, old)):
            line = (lines[i] if i < n else "")[:width]
            sys.stdout.write("\r" + line + "\x1b[K\n")
        if max(n, old) > n:
            sys.stdout.write(f"\x1b[{max(n, old) - n}A")
        sys.stdout.flush()
        self._block_height = n
        self._last_block = list(lines)

    def _redraw_block(self) -> None:
        """Redraw the last drawn block (after a normal line was printed)."""
        if self._last_block:
            self._draw_block(self._last_block)

    def _clear_block(self) -> None:
        """Clear the drawn live block, leaving the cursor at its start.

        The remembered copy (_last_block) survives the clear: the normal
        output paths clear the block, print their line, and then
        _redraw_block() puts the block back below it. The fixed-lines path
        drops the copy explicitly — history replaced the block.
        """
        if not self._block_height:
            return
        sys.stdout.write(f"\x1b[{self._block_height}A")
        for _ in range(self._block_height):
            sys.stdout.write("\r\x1b[K\n")
        sys.stdout.write(f"\x1b[{self._block_height}A")
        sys.stdout.flush()
        self._block_height = 0

    @property
    def buffered_steps(self) -> list[tuple[str, dict[str, Any], int | None, int | None]]:
        return self._buffered_steps

    @property
    def buffered_fixed(self) -> list[str]:
        return self._buffered_fixed
