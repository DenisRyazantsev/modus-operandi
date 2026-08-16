"""Shared terminal-editor resolution for the pipeline scripts.

One responsibility: resolve the editor used to open a file in the terminal
($VISUAL, then $EDITOR, then nano, then vi). The chain lives in exactly one
place because two consumers need it — the run-pipeline wrapper's ADR
feedback gate (feedback_editor.py) and the spec-run launcher's `edit`
command (edit_command.py) — and it must behave identically for both. The
installer copies this module next to both consumers (scripts/ and the
launcher's bin dir).
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys


def resolve_editor() -> list[str] | None:
    """Resolve the terminal editor for a file.

    Order: $VISUAL, then $EDITOR, then nano, then vi. A $VISUAL/$EDITOR
    value may carry arguments (`code --wait`) and is split like a shell
    command line; a malformed value (e.g. an unbalanced quote) is skipped
    with a warning, and a candidate whose binary is not on PATH falls
    through to the next one. None means no editor is available at all and
    the caller must fall back to manual input.
    """
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var)
        if not value:
            continue
        try:
            cmd = shlex.split(value)
        except ValueError as exc:
            print(
                f"warning: {var} is malformed ({exc}); skipping it",
                file=sys.stderr,
            )
            continue
        if cmd and shutil.which(cmd[0]):
            return cmd
    for name in ("nano", "vi"):
        if shutil.which(name):
            return [name]
    return None
