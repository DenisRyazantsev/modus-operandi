#!/usr/bin/env python3
"""spec-run - global launcher for the spec-kit-llm-client pipelines.

Installed once into ~/.local/bin by install.py and callable from any project
directory, without `specify init` required. It delegates to the installed
run-pipeline.py wrapper with the absolute workflow path, so runs keep the
timestamps, live step output, run statistics and the victory sound.
`spec-run edit` opens the installed config.yml in your terminal editor and
re-applies it on exit, so the next run already uses the new settings.

The launcher resolves every installed path at runtime: run-pipeline.py, both
workflows and config.yml come from the config base directory derived from
XDG_CONFIG_HOME/$HOME, and the repo's install.py path (used by `edit`) is
read from the install-path.txt file the installer writes into the config
directory. Nothing is baked into this file at install time.

This file is the entry point of a module split, one concern per file: the
`edit` execution flow lives in edit_command.py and the shared editor
resolution in editor.py (the same editor.py the run-pipeline wrapper uses
for its feedback gate); the exceptions package ships one class per file.
This module owns the launcher dispatch and re-exports the shared names so
the launcher keeps its single import surface.

Usage:
  spec-run adr "feature description" [-i key=value ...]
  spec-run task "task description" [-i key=value ...]
  spec-run review [--branch-diff]
  spec-run edit
  spec-run --backend cursor adr "feature description"   # override the backend for this run
  spec-run --help | -h

Examples:
  spec-run adr "build a kanban board"
  spec-run adr "build a kanban board" -i task_id=kanban
  spec-run task "add a dark mode toggle"
  spec-run task "add a dark mode toggle" -i task_id=dark-mode
  spec-run --backend cursor adr "build a kanban board"
  spec-run review
  spec-run review --branch-diff
  spec-run edit
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# The exceptions package (one class per file) and the edit/editor modules
# ship next to this launcher — source: pipeline_scripts/, installed: <bin
# dir>/. `__file__` is the launcher itself, so its directory is the one place
# the package is guaranteed to be found, however the launcher is loaded (as
# an installed script, through exec, or by tests via importlib).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edit_command import _run_edit
from editor import resolve_editor
from exceptions import EditRequested, HelpRequested, InvalidInvocation

# Public surface of the launcher: the pure mapping, the shared editor
# resolution and the signals, so tests and callers keep a single import
# target (the spec_run module).
__all__ = [
    "ADR_WORKFLOW",
    "CONFIG",
    "INSTALL_PATH_FILE",
    "REVIEW_WORKFLOW",
    "RUN_PIPELINE",
    "TASK_WORKFLOW",
    "USAGE",
    "build_command",
    "print_usage",
    "resolve_editor",
]


def _config_base() -> Path:
    """The config root the installer writes into (XDG_CONFIG_HOME or ~/.config)."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _scripts_dir() -> Path:
    return _config_base() / "opencode" / "scripts"


def _config_dir() -> Path:
    return _config_base() / "spec-kit-llm-client"


# Paths of the installed pipeline, resolved from the launcher's location
# (both live under the config base, so no values are baked at install time).
RUN_PIPELINE = str(_scripts_dir() / "run-pipeline.py")
ADR_WORKFLOW = str(_config_dir() / "adr-pipeline.yml")
REVIEW_WORKFLOW = str(_config_dir() / "review-pipeline.yml")
TASK_WORKFLOW = str(_config_dir() / "task-pipeline.yml")
CONFIG = str(_config_dir() / "config.yml")

# The repo's install.py path, recorded by the installer for `spec-run edit`.
INSTALL_PATH_FILE = _config_dir() / "install-path.txt"

USAGE = """Usage: spec-run <subcommand> [args]

  spec-run --backend <opencode|cursor> <subcommand> [args]
      Override the configured backend for this run (the flag must precede
      the subcommand; the config `backend:` remains the default).

  spec-run adr "feature description" [-i key=value ...]
      Run the full ADR pipeline for the feature (ADR -> implementation ->
      review). All non-flag arguments after `adr` are joined into the feature
      input; -i key=value arguments are passed through to the workflow.

  spec-run task "task description" [-i key=value ...]
      Run the full task pipeline for the task (motivation study -> research ->
      ADR -> implementation -> review). All non-flag arguments after `task`
      are joined into the task input; -i key=value arguments are passed
      through to the workflow.

  spec-run review [--branch-diff] [-i key=value ...]
      Review the project code (default: the whole codebase). With --branch-diff
      only the changes between the current branch and the default branch.

  spec-run edit
      Open the installed config.yml in your terminal editor and re-apply it
      on exit (editor: VISUAL, then EDITOR, then nano, then vi).

  spec-run --help | -h
      Print this help and exit 0.

Examples:
  spec-run adr "build a kanban board"
  spec-run adr "build a kanban board" -i task_id=kanban
  spec-run --backend cursor adr "build a kanban board"
  spec-run review
  spec-run review --branch-diff
  spec-run edit
"""


def build_command(argv: list[str]) -> list[str]:
    """Map spec-run argv to the command to execute (pure dispatch).

    Raises HelpRequested for `--help`/`-h`, EditRequested for `edit` and
    InvalidInvocation for an unusable invocation; it never prints anything, so
    mapping stays separate from presentation. The caller owns the usage output
    and the exit code. A leading global `--backend <opencode|cursor>` flag
    (before the subcommand) is consumed and forwarded to run-pipeline.py.
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
    if head == "adr":
        return _build_adr_command(rest, backend)
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
    raise InvalidInvocation


def _build_text_input_command(
    rest: list[str], backend: str | None, workflow: str, input_key: str
) -> list[str]:
    """Map the text-input subcommands (adr/task) to a run-pipeline command.

    Both subcommands share one parsing concern: the non-flag arguments are
    joined into a single text input (`-i <input_key>=<joined text>`), while
    `-i key=value` pairs (two argv elements) and `-i key=value` single
    elements are passed through to the workflow unchanged. A dangling `-i`
    without a value is an invalid invocation, not a flag to forward: specify
    would fail with a confusing parser error, while other bad calls get a
    clear usage. The space in the `-i ` prefix is required so text like
    `-integration` is not mistaken for an input.
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
    cmd.append("-i")
    cmd.append(f"{input_key}={text}")
    cmd.extend(passed)
    return cmd


def _build_adr_command(rest: list[str], backend: str | None = None) -> list[str]:
    return _build_text_input_command(rest, backend, ADR_WORKFLOW, "feature")


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


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        cmd = build_command(argv)
    except HelpRequested:
        print_usage()
        return 0
    except InvalidInvocation:
        print_usage(sys.stderr)
        return 1
    except EditRequested:
        return _run_edit(CONFIG, INSTALL_PATH_FILE)
    try:
        # os.execv replaces this process with run-pipeline.py, so its live
        # output, timestamps and exit code pass through unchanged; it returns
        # only when exec fails, which is why return 1 follows.
        os.execv(cmd[0], cmd)
    except OSError as exc:
        print(f"error: cannot run {cmd[0]}: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
