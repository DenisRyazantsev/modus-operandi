"""The `spec-run edit` flow: open the installed config in the editor and re-apply it.

One responsibility: run the `edit` subcommand — resolve the terminal editor
(shared editor.py chain), open the installed config.yml, and re-apply it
through the package's ``installer.apply()`` so the next run already uses the
new settings. Paths are passed in by the launcher, which owns the
installed-path resolution.
"""

from __future__ import annotations

import subprocess
import sys

from spec_run import InstallError, Paths, installer
from spec_run.editor import resolve_editor


def _launch_editor(editor_cmd: list[str]) -> int | None:
    # The editor runs as a child process inheriting stdin/stdout so
    # full-screen editors keep working. Returns the editor's exit code, or
    # None when the editor could not be started (an error is printed then);
    # None is distinguishable from an editor that ran and exited with 1.
    try:
        return subprocess.run(editor_cmd, check=False).returncode
    except OSError as exc:
        print(
            f"error: cannot start editor {editor_cmd[0]}: {exc}",
            file=sys.stderr,
        )
        return None


def _apply_config(layout: Paths) -> int:
    # Re-apply the (possibly edited) config through the package: it reloads
    # and validates config.yml, re-renders every artifact and records the
    # install version, without the install-time prerequisite checks or the
    # next-steps output. A config that fails validation surfaces here and
    # aborts `edit` with an error.
    try:
        installer.apply(layout)
    except (InstallError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("config applied - agents, scripts and workflows re-rendered")
    return 0


def _run_edit(config: str, layout: Paths) -> int:
    # `edit` takes no arguments; the config path and the install layout are
    # derived by the launcher. Resolve and run the editor, then re-apply the
    # config whenever the editor actually launched. The editor's own exit
    # code does not gate the apply: a user can save a valid edit and still
    # close the editor non-zero (vim :cq, ...), and apply() re-validates the
    # config anyway, failing loudly on an invalid edit. Only a failure to
    # start the editor aborts.
    editor_cmd = resolve_editor()
    if editor_cmd is None:
        print(
            "error: no editor found; set VISUAL or EDITOR, or install nano/vi",
            file=sys.stderr,
        )
        return 1
    if _launch_editor(editor_cmd + [config]) is None:
        return 1
    return _apply_config(layout)
