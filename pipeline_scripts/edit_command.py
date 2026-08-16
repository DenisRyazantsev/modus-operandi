"""The `spec-run edit` flow: open the installed config in the editor and re-apply it.

One responsibility: run the `edit` subcommand — resolve the terminal editor
(shared editor.py chain), open the installed config.yml, and re-apply it
through the repo's install.py (`--apply`) so the next run already uses the
new settings. Paths are passed in by the launcher, which owns the
installed-path resolution.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from editor import resolve_editor


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


def _install_py(install_path_file: Path) -> str:
    """Return the recorded repo install.py path, or "" when not recorded.

    The installer writes the absolute path of the repo's install.py into
    install-path.txt; `spec-run edit` needs it to re-apply the config. The
    path cannot be derived from the launcher's own location (the repo clone
    may live anywhere), so a missing file means the installer metadata is
    gone (clone moved/deleted) and edit must fail with a readable error.
    """
    try:
        return install_path_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _apply_config(install_path_file: Path) -> int:
    # Re-apply the (possibly edited) config through the repo installer: it
    # reloads and validates config.yml, re-renders every artifact and verifies
    # the result, without the install-time prerequisite/dependency checks or
    # the next-steps output. A config that fails validation surfaces here and
    # aborts `edit` with the installer's exit code.
    install_py = _install_py(install_path_file)
    if not install_py:
        print(
            f"error: cannot find the recorded install.py path ({install_path_file}); rerun "
            "install.py from the repo clone to record it",
            file=sys.stderr,
        )
        return 1
    result = subprocess.run([sys.executable, install_py, "--apply"], check=False)
    if result.returncode == 0:
        print("config applied - agents, scripts and workflows re-rendered")
    return result.returncode


def _run_edit(config: str, install_path_file: Path) -> int:
    # `edit` takes no arguments; the config path is derived from the
    # launcher's location at import time. Resolve and run the editor, then
    # re-apply the config whenever the editor actually launched. The editor's
    # own exit code does not gate the apply: a user can save a valid edit and
    # still close the editor non-zero (vim :cq, ...), and `--apply`
    # re-validates the config anyway, failing loudly on an invalid edit. Only
    # a failure to start the editor aborts.
    editor_cmd = resolve_editor()
    if editor_cmd is None:
        print(
            "error: no editor found; set VISUAL or EDITOR, or install nano/vi",
            file=sys.stderr,
        )
        return 1
    if _launch_editor(editor_cmd + [config]) is None:
        return 1
    return _apply_config(install_path_file)
