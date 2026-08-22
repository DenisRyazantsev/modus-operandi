"""The `modus-operandi edit` flow: open the installed config in the editor and re-apply it.

One responsibility: run the `edit` subcommand — resolve the terminal editor
(shared editor.py chain), open the installed config.yml, and re-apply it
through the package's ``installer.apply()`` so the next run already uses the
new settings. The config is backed up before the editor opens and restored
when validation fails, so an invalid edit never leaves a broken config on
disk. Paths are passed in by the launcher, which owns the installed-path
resolution.
"""

from __future__ import annotations

import subprocess as subprocess
import sys
from pathlib import Path

from modus_operandi import InstallError, Paths, installer
from modus_operandi.editor import resolve_editor


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


def _backup_config(config: str) -> bytes | None:
    # Snapshot the config before the editor opens so an invalid edit can be
    # rolled back. None means the file could not be read (an error is printed
    # then) and `edit` aborts without launching the editor.
    try:
        return Path(config).read_bytes()
    except OSError as exc:
        print(f"error: cannot read {config}: {exc}", file=sys.stderr)
        return None


def _restore_config(config: str, backup: bytes) -> None:
    try:
        Path(config).write_bytes(backup)
    except OSError as exc:
        print(f"error: cannot restore {config}: {exc}", file=sys.stderr)


def _apply_config(config: str, layout: Paths, backup: bytes) -> int:
    # Re-apply the (possibly edited) config through the package: it reloads
    # and validates config.yml, re-renders every artifact and records the
    # install version, without the install-time prerequisite checks or the
    # next-steps output. A config that fails validation is rolled back to the
    # pre-edit snapshot, so the user's invalid edit never sticks on disk.
    try:
        installer.apply(layout)
    except (InstallError, OSError, ValueError, KeyError) as exc:
        _restore_config(config, backup)
        print(
            f"error: config.yml is invalid, changes not saved: {exc}",
            file=sys.stderr,
        )
        return 1
    print("config applied - agents, scripts and workflows re-rendered")
    return 0


def _run_edit(config: str, layout: Paths) -> int:
    # `edit` takes no arguments; the config path and the install layout are
    # derived by the launcher. Resolve and run the editor, then re-apply the
    # config whenever the editor actually launched. The editor's own exit
    # code does not gate the apply: a user can save a valid edit and still
    # close the editor non-zero (vim :cq, ...), and apply() re-validates the
    # config anyway, rolling back an invalid edit. Only a failure to start
    # the editor aborts. Leaving the editor without changing the file (the
    # user quit without saving) is detected byte-for-byte against the
    # pre-edit snapshot and skips the apply entirely.
    editor_cmd = resolve_editor()
    if editor_cmd is None:
        print(
            "error: no editor found; set VISUAL or EDITOR, or install nano/vi",
            file=sys.stderr,
        )
        return 1
    backup = _backup_config(config)
    if backup is None:
        return 1
    if _launch_editor(editor_cmd + [config]) is None:
        return 1
    try:
        current = Path(config).read_bytes()
    except OSError:
        # The editor removed the file: treat it as a change so apply() runs
        # and its validation error restores the snapshot.
        current = None
    if current is not None and current == backup:
        print("config unchanged - nothing to apply")
        return 0
    return _apply_config(config, layout, backup)
