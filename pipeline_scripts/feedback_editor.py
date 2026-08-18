"""The feedback gates' editor interaction.

One responsibility: own the feedback.md file and the editor for the
feedback gates — create the file (never overwriting), resolve the editor,
open it, and on editor close answer the gate with `continue`. The platform
resolution itself lives in editor.py. The module is shared with the
spec-run launcher (same file, both install targets), but `spec-run edit`
deliberately uses the terminal chain (`resolve_editor`) — the platform
resolution (`resolve_feedback_editor`) is feedback-gate-only.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from pathlib import Path

from _run_pipeline_common import extract_numbered_questions, questions_source_file
from editor import resolve_feedback_editor


def create_feedback_file(path: Path, source_doc: Path | None = None) -> None:
    """Create the feedback.md for the revise gate.

    Never overwrites an existing file: the planner may have written one, or
    the user may have started writing during an earlier fallback. A NEW file
    is seeded (ADR-0012) with the numbered questions of the source
    document's open-questions section (study.md for the motivation gate,
    adr.md for the ADR gate); a missing document — or a document without
    questions — leaves the file empty.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    path.touch()
    questions: list[str] = []
    if source_doc is not None:
        with contextlib.suppress(OSError, UnicodeDecodeError):
            questions = extract_numbered_questions(source_doc.read_text(encoding="utf-8"))
    if questions:
        path.write_text("\n".join(questions) + "\n", encoding="utf-8")


def open_feedback_editor(
    state_dir: str,
    pause: threading.Event,
    master_fd: int,
    step_id: str | None,
) -> bool:
    """Own the feedback gates' editor interaction.

    Any step whose id contains "feedback-gate" routes here (the ADR revise
    gate, the motivation clarify gate — the wrapper recognizes them by the
    shared marker, so the handling is identical for all of them). Pauses
    stdin forwarding, creates feedback.md in the current task dir (never
    overwriting; a NEW file is seeded with the numbered open questions of
    the gate's document — study.md for a `motivation` gate, adr.md for an
    `adr` gate — so the questions are in front of the user while writing,
    ADR-0012), opens it in the platform editor and, on editor close,
    answers the gate with `continue` so the workflow continues (the revise
    step reads feedback.md).
    The editor resolution (editor.py) returns a mode: "waited" (macOS
    TextEdit or the terminal chain) runs the editor blocking and the wrapper
    answers the gate; "detached" (Linux GUI in a separate window) launches
    the editor and leaves the gate interactive — the user closes the window
    and presses `continue`. Returns True when the wrapper answered the gate;
    False on fallback — no TTY, no editor, or a detached launch — where the
    file is still created, forwarding is left running and the gate stays
    interactive for manual input.
    """
    task_dir = Path.cwd() / state_dir / "tasks" / "current"
    source_doc: Path | None = None
    source_name = questions_source_file(step_id or "")
    if source_name is not None:
        source_doc = task_dir / source_name
    feedback_path = task_dir / "feedback.md"
    create_feedback_file(feedback_path, source_doc)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    resolved = resolve_feedback_editor()
    if resolved is None:
        return False
    mode, editor = resolved
    if mode == "detached":
        # Linux GUI: launch in a separate window and leave the gate
        # interactive — the user closes the window and presses continue.
        # Forwarding is never paused: the continue answer comes from the
        # terminal, not from this wrapper.
        try:
            subprocess.Popen(
                [*editor, str(feedback_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            print(
                f"error: cannot start editor {editor[0]}: {exc}",
                file=sys.stderr,
            )
            return False
        return False
    # waited: run the editor blocking (it inherits the real terminal, not the
    # pty, so there is no race with the gate's input()), then answer the
    # gate.
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
        # "continue" is the option declared on the feedback-gate steps
        # (options: [continue, abort] in the installed workflows); the
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
