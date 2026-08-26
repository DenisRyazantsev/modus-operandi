#!/usr/bin/env python3
"""modus-operandi - global launcher for the modus-operandi pipelines (console-script entry).

Installed by pip as the ``modus-operandi`` console script and callable from any
project directory, without `specify init` required. It delegates to the
installed run-pipeline.py wrapper with the absolute workflow path, so runs
keep the timestamps, live step output, run statistics and the victory sound.
`modus-operandi edit` opens the installed config.yml in your terminal editor and
applies it on save and close — a valid config is applied, an invalid one is
rolled back, an unchanged one is left as-is. `modus-operandi uninstall` removes
the rendered pipeline files from the machine.

The launcher resolves every installed path at runtime: run-pipeline.py, both
workflows and config.yml come from the config base directory derived from
XDG_CONFIG_HOME/$HOME. Nothing is baked into this file at install time.
Before dispatching a task/review/edit run, the launcher bootstraps the
installation (ensure_installed): when the rendered artifacts are missing or
stale, it renders them from the package data and prints one status line.

This module is the entry point of a module split, one concern per file: the
`edit` execution flow lives in edit_command.py, the shared editor resolution
in editor.py (the same editor.py the run-pipeline wrapper uses for its
feedback gate), the exceptions package ships one class per file, the
bootstrap (first-run/update render) lives in bootstrap.py and the
`uninstall` flow in uninstall.py.

Usage:
  modus-operandi task "task description" [-i key=value ...]
  modus-operandi task path/to/task-description.txt [-i key=value ...]
  modus-operandi review [--branch-diff]
  modus-operandi edit
  modus-operandi uninstall [--yes]
  modus-operandi --backend cursor task "task description"   # override the backend for this run
  modus-operandi --help | -h
  modus-operandi --version | -V   # print the version and exit 0

Examples:
  modus-operandi task "add a dark mode toggle"
  modus-operandi task docs/tasks/dark-mode.md
  modus-operandi task "add a dark mode toggle" -i task_id=dark-mode
  modus-operandi --backend cursor task "add a dark mode toggle"
  modus-operandi review
  modus-operandi review --branch-diff
  modus-operandi edit
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from modus_operandi import __version__, bootstrap, paths, uninstall
from modus_operandi.edit_command import _run_edit
from modus_operandi.editor import resolve_editor
from modus_operandi.exceptions import (
    EditRequested,
    HelpRequested,
    InvalidInvocation,
    UninstallRequested,
    VersionRequested,
)

# Public surface of the launcher: the pure mapping, the shared editor
# resolution and the signals, so tests and callers keep a single import
# target (the modus_operandi.cli module).
__all__ = [
    "CONFIG",
    "REVIEW_WORKFLOW",
    "RUN_PIPELINE",
    "TASK_WORKFLOW",
    "USAGE",
    "EditRequested",
    "HelpRequested",
    "InvalidInvocation",
    "UninstallRequested",
    "VersionRequested",
    "build_command",
    "print_usage",
    "print_version",
    "resolve_editor",
]


def _config_base() -> Path:
    """The config root the installer writes into (XDG_CONFIG_HOME or ~/.config)."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _scripts_dir() -> Path:
    return _config_base() / "opencode" / "scripts"


def _config_dir() -> Path:
    return _config_base() / "modus-operandi"


# Paths of the installed pipeline, derived from the config base at runtime
# (XDG_CONFIG_HOME or ~/.config), so nothing is baked at install time.
_LAYOUT = paths.build_paths_from_config_base(_config_base())
RUN_PIPELINE = str(_scripts_dir() / "run-pipeline.py")
REVIEW_WORKFLOW = str(_config_dir() / "review-pipeline.yml")
TASK_WORKFLOW = str(_config_dir() / "task-pipeline.yml")
CONFIG = str(_config_dir() / "config.yml")

USAGE = """Usage: modus-operandi <subcommand> [args]

  modus-operandi --backend <opencode|cursor> <subcommand> [args]
      Override the configured backend for this run (the flag must precede
      the subcommand; the config `backend:` remains the default).

  modus-operandi task "task description" [-i key=value ...]
  modus-operandi task path/to/task-description.txt [-i key=value ...]
      Run the full task pipeline for the task (motivation study -> research ->
      ADR -> implementation -> review). All non-flag arguments after `task`
      are joined into the task input; a single argument naming an existing
      file is read as the task description instead (text and file input are
      mutually exclusive); -i key=value arguments are passed through to the
      workflow.

  modus-operandi review [--branch-diff] [-i key=value ...]
      Review the project code (default: the whole codebase). With --branch-diff
      only the changes between the current branch and the default branch.

  modus-operandi edit
      Open the installed config.yml in your terminal editor (VISUAL, then
      EDITOR, then nano, then vi). On save and close it validates the file:
      a valid config is applied, an invalid one is rolled back, and one that
      was left unchanged is not re-applied.

  modus-operandi uninstall [--yes]
      Remove the rendered pipeline files (~/.config/modus-operandi and the
      modus-operandi files under ~/.config/opencode), then run
      `pip uninstall modus-operandi` to remove the package itself. Asks for
      confirmation unless --yes is given.

  modus-operandi --help | -h
      Print this help and exit 0.

  modus-operandi --version | -V
      Print the version and exit 0.

Examples:
  modus-operandi task "add a dark mode toggle"
  modus-operandi task docs/tasks/dark-mode.md
  modus-operandi task "add a dark mode toggle" -i task_id=dark-mode
  modus-operandi --backend cursor task "add a dark mode toggle"
  modus-operandi review
  modus-operandi review --branch-diff
  modus-operandi edit
"""


def build_command(argv: list[str]) -> list[str]:
    """Map modus-operandi argv to the command to execute (pure dispatch).

    Raises HelpRequested for `--help`/`-h`, VersionRequested for
    `--version`/`-V`, EditRequested for `edit`,
    UninstallRequested for `uninstall` (carrying the `--yes` flag) and
    InvalidInvocation for an unusable invocation; it never prints anything,
    so mapping stays separate from presentation. The caller owns the usage
    output and the exit code. A leading global `--backend <opencode|cursor>`
    flag (before the subcommand) is consumed and forwarded to
    run-pipeline.py.
    """
    if not argv:
        raise InvalidInvocation
    backend: str | None = None
    head, rest = argv[0], argv[1:]
    if head == "--backend":
        if not rest:
            raise InvalidInvocation
        backend = rest[0]
        if backend not in ("opencode", "cursor"):
            raise InvalidInvocation
        rest = rest[1:]
        if not rest:
            raise InvalidInvocation
        head, rest = rest[0], rest[1:]
    if head in ("-h", "--help"):
        raise HelpRequested
    if head in ("-V", "--version"):
        raise VersionRequested
    if head == "task":
        return _build_task_command(rest, backend)
    if head == "review":
        return _build_review_command(rest, backend)
    if head == "edit":
        # `edit` takes no arguments: anything after the subcommand is ignored.
        # Editor resolution is environment-dependent (os.environ, shutil.which)
        # and belongs to the edit execution path (edit_command._run_edit), not
        # to this pure mapping; a signal keeps the subcommand ->
        # execution-path decision in one place.
        raise EditRequested
    if head == "uninstall":
        # `--yes` skips the confirmation prompt of the uninstall flow; extra
        # arguments are ignored like for `edit`.
        raise UninstallRequested("--yes" in rest)
    raise InvalidInvocation


def _escape_shell_text(text: str) -> str:
    """Escape \\ " ` $ with a backslash (backslash first) for the
    double-quoted shell contexts the pipeline interpolates the text into."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def _path_exists(path: str) -> bool:
    """True when path names an existing file. A string that cannot be a
    filename (e.g. too long, triggering ENAMETOOLONG) is not a file."""
    try:
        return Path(path).is_file()
    except OSError:
        return False


def _build_text_input_command(
    rest: list[str], backend: str | None, workflow: str, input_key: str
) -> list[str]:
    """Map the text-input subcommands (task) to a run-pipeline command.

    The non-flag arguments are joined into a single text input
    (`-i <input_key>=<joined text>`), while `-i key=value` pairs (the two
    argv elements `-i` and `key=value`) and the combined single element
    `"-i key=value"` are passed through to the workflow unchanged. A
    dangling `-i` without a value is an invalid
    invocation, not a flag to forward: specify would fail with a confusing
    parser error, while other bad calls get a clear usage. The space in the
    `-i ` prefix is required so text like `-integration` is not mistaken for
    an input.
    """
    cmd = [RUN_PIPELINE]
    if backend:
        cmd += ["--backend", backend]
    cmd.append(workflow)
    text_parts: list[str] = []
    passed: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "-i":
            if i + 1 >= len(rest):
                # A dangling `-i` without a value is an invalid invocation,
                # not a flag to forward: specify would fail with a confusing
                # parser error, while other bad calls get a clear usage.
                raise InvalidInvocation
            # Shell-style pair: `-i key=value` as two argv elements.
            passed.append(arg)
            passed.append(rest[i + 1])
            i += 2
            continue
        if arg.startswith("-i "):
            # Combined single element: `-i key=value`. The space is required
            # so text like `-integration` is not mistaken for an input.
            passed.append(arg)
        else:
            text_parts.append(arg)
        i += 1
    text = " ".join(text_parts)
    if not text:
        raise InvalidInvocation
    try:
        is_file = Path(text_parts[0]).is_file()
    except OSError:
        is_file = False
    if len(text_parts) == 1 and is_file:
        # File mode (ADR-0018): a single argument naming an existing file is
        # read as the task description.
        try:
            text = Path(text_parts[0]).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise InvalidInvocation(f"cannot read task file {text_parts[0]!r}: {exc}") from exc
        if not text.strip():
            raise InvalidInvocation(f"task file {text_parts[0]!r} is empty")
    elif any(_path_exists(part) for part in text_parts):
        raise InvalidInvocation("pass either a single task file or task text, not both")
    # The pipeline interpolates the text into double-quoted shell arguments
    # and validate-inputs accepts only the escaped forms (ADR-0018): escape
    # uniformly for text and file input, so the user never sees the check.
    text = _escape_shell_text(text)
    cmd.append("-i")
    cmd.append(f"{input_key}={text}")
    cmd.extend(passed)
    return cmd


def _build_task_command(rest: list[str], backend: str | None = None) -> list[str]:
    return _build_text_input_command(rest, backend, TASK_WORKFLOW, "task")


def _build_review_command(rest: list[str], backend: str | None = None) -> list[str]:
    cmd = [RUN_PIPELINE]
    if backend:
        cmd += ["--backend", backend]
    cmd.append(REVIEW_WORKFLOW)
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--branch-diff":
            cmd.append("-i")
            cmd.append("branch-diff=true")
        elif arg == "-i":
            if i + 1 >= len(rest):
                raise InvalidInvocation
            cmd.append(arg)
            cmd.append(rest[i + 1])
            i += 2
            continue
        else:
            cmd.append(arg)
        i += 1
    return cmd


def print_usage(stream: Any = None) -> None:
    """Print the usage text; defaults to stdout, pass sys.stderr for errors."""
    if stream is None:
        stream = sys.stdout
    print(USAGE, file=stream)


def print_version(stream: Any = None) -> None:
    """Print the version line; defaults to stdout. Unlike print_usage, no
    error path uses stderr here — the stream parameter mirrors print_usage
    for symmetry and testability."""
    if stream is None:
        stream = sys.stdout
    print(f"modus-operandi {__version__}", file=stream)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        try:
            cmd = build_command(argv)
        except HelpRequested:
            print_usage()
            return 0
        except VersionRequested:
            print_version()
            return 0
        except InvalidInvocation as exc:
            if str(exc):
                print(f"error: {exc}", file=sys.stderr)
            print_usage(sys.stderr)
            return 1
        except EditRequested:
            # The edit flow never runs the backend CLI, so the
            # tool-presence prerequisite check is skipped: a user who
            # uninstalled the active backend must still be able to edit the
            # config (e.g. to switch backends). The bootstrap render is
            # best-effort on this path: a stale install marker with an
            # INVALID config.yml must not gate the editor either — fixing a
            # broken config is exactly what `edit` is for, and _run_edit
            # re-validates when the editor closes (rolling back an invalid
            # edit), so a failed bootstrap here cannot apply anything.
            bootstrap.ensure_installed(_LAYOUT, check_prereqs=False)
            return _run_edit(CONFIG, _LAYOUT)
        except UninstallRequested as exc:
            return uninstall.do_uninstall(_LAYOUT, exc.yes)
        if bootstrap.ensure_installed(_LAYOUT) != 0:
            return 1
        try:
            # os.execv replaces this process with run-pipeline.py, so its live
            # output, timestamps and exit code pass through unchanged; it returns
            # only when exec fails, which is why return 1 follows.
            os.execv(cmd[0], cmd)
        except OSError as exc:
            print(f"error: cannot run {cmd[0]}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # Ctrl+C at a prompt (e.g. the uninstall confirmation) is a normal
        # way to bail out: a quiet exit 130, not a traceback.
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
