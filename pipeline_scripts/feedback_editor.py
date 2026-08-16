"""The ADR revise feedback gate's editor interaction.

One responsibility: own the feedback.md file and the terminal editor for
the revise gate — create the file (never overwriting), resolve the editor,
open it, and on editor close answer the gate with `continue`. The editor
resolution itself lives in editor.py, shared with the spec-run launcher.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from pathlib import Path

from editor import resolve_editor


def create_feedback_file(path: Path) -> None:
    """Create the empty feedback.md for the revise gate.

    Never overwrites an existing file: the planner may have written one, or
    the user may have started writing during an earlier fallback.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()


def open_feedback_editor(
    feedback_path: Path, pause: threading.Event, master_fd: int
) -> bool:
    """Own the ADR revise feedback gate.

    Pauses stdin forwarding, creates feedback.md (never overwriting), opens
    it in the terminal editor (which inherits the real terminal, not the
    pty, so there is no race with the gate's input()) and, on editor close,
    answers the gate with `continue` so the workflow continues (adr-revise
    reads feedback.md). Returns True when the wrapper answered the gate;
    False on fallback — no TTY or no editor on PATH — where the file is
    still created, forwarding is left running and the gate stays interactive
    for manual input.
    """
    create_feedback_file(feedback_path)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    editor = resolve_editor()
    if editor is None:
        return False
    pause.set()
    try:
        try:
            subprocess.run([*editor, str(feedback_path)], check=False)
        except OSError as exc:
            print(
                f"error: cannot start editor {editor[0]}: {exc}",
                file=sys.stderr,
            )
            return False
        # "continue" is the option declared on the adr-feedback-gate step
        # (options: [continue, abort] in the installed adr-pipeline.yml); the
        # wrapper hardcodes it because it has no parsed handle on the
        # workflow's options, so this string is a cross-file contract, not a
        # free-form answer — a mismatch makes specify reject it and the gate
        # silently degrades to manual input. The answer is written while
        # forwarding is still paused: it is guaranteed to be the first thing
        # the gate's input() reads.
        with contextlib.suppress(OSError):
            os.write(master_fd, b"continue\n")
        return True
    finally:
        pause.clear()
