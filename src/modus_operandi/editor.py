"""Shared editor resolution for the pipeline scripts.

Two concerns, one module: the terminal-editor chain ($VISUAL, then $EDITOR,
then nano, then vi) used by `modus-operandi edit` and as the feedback gates'
no-GUI fallback, and the platform editor resolution for the feedback gates
themselves (macOS TextEdit, Linux GNOME Text Editor in a separate window,
ADR-0011). The chain lives in exactly one place because several consumers
need it — the run-pipeline wrapper's feedback gates (feedback_editor.py) and
the modus-operandi launcher's `edit` command (edit_command.py) — and it must behave
identically for both.

The repo ships two byte-identical copies on purpose: this module is imported
by the pip console script (`modus-operandi edit`), and the copy under
data/pipeline_scripts/ is rendered into ~/.config/opencode/scripts/ for the
installed run-pipeline wrapper's feedback gate (the installed scripts are
self-contained and import their siblings from their own directory).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
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


def resolve_feedback_editor() -> tuple[str, list[str]] | None:
    """Resolve the platform editor for the feedback gates (ADR-0011).

    Returns (mode, cmd): mode is "waited" — run the editor blocking and
    answer the gate with `continue` on close — or "detached" — launch it in
    a separate window and leave the gate interactive (the user presses
    `continue`). None means no editor is available at all.

    macOS: TextEdit via `open -a TextEdit -W` (always installed; the -W flag
    blocks until the app closes), waited. Linux: GNOME Text Editor in a
    separate window — Flatpak first (checked via `flatpak info
    org.gnome.TextEditor`), then the RPM binary, then the generic desktop
    opener (gio, then xdg-open) — all detached, since these launchers return
    immediately. Fallback: the terminal chain ($VISUAL, $EDITOR, nano, vi),
    waited.
    """
    if sys.platform == "darwin":
        return "waited", ["open", "-a", "TextEdit", "-W"]
    if sys.platform.startswith("linux"):
        if shutil.which("flatpak"):
            try:
                result = subprocess.run(
                    ["flatpak", "info", "org.gnome.TextEditor"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except OSError:
                result = None
            if result is not None and result.returncode == 0:
                return "detached", ["flatpak", "run", "org.gnome.TextEditor"]
        for name in ("gnome-text-editor", "gio", "xdg-open"):
            if shutil.which(name):
                if name == "gio":
                    return "detached", ["gio", "open"]
                return "detached", [name]
    editor = resolve_editor()
    if editor is None:
        return None
    return "waited", editor
