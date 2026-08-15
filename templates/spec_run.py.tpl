#!/usr/bin/env python3
"""spec-run - global launcher for the spec-kit-llm-client pipelines.

Installed once into ~/.local/bin by install.py and callable from any project
directory, without `specify init` required. It delegates to the installed
run-pipeline.py wrapper with the absolute workflow path, so runs keep the
timestamps, live step output, run statistics and the victory sound.
`spec-run edit` opens the installed config.yml in your terminal editor and
re-applies it on exit, so the next run already uses the new settings.

Usage:
  spec-run adr "feature description" [-i key=value ...]
  spec-run review [--branch-diff]
  spec-run edit
  spec-run --help | -h

Examples:
  spec-run adr "build a kanban board"
  spec-run adr "build a kanban board" -i task_id=kanban
  spec-run review
  spec-run review --branch-diff
  spec-run edit
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

# Absolute paths baked in at install time; rerun install.py after moving
# ~/.config/spec-kit-llm-client, ~/.config/opencode or the repo clone.
RUN_PIPELINE = "${run_pipeline}"
ADR_WORKFLOW = "${adr_workflow}"
REVIEW_WORKFLOW = "${review_workflow}"
INSTALL_PY = "${install_py}"
CONFIG = "${config}"

USAGE = """Usage: spec-run <subcommand> [args]

  spec-run adr "feature description" [-i key=value ...]
      Run the full ADR pipeline for the feature (ADR -> implementation ->
      review). All non-flag arguments after `adr` are joined into the feature
      input; -i key=value arguments are passed through to the workflow.

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
  spec-run review
  spec-run review --branch-diff
  spec-run edit
"""


def build_command(argv: list[str]) -> list[str]:
    """Map spec-run argv to the command to execute (pure dispatch).

    Raises HelpRequested for `--help`/`-h`, EditRequested for `edit` and
    InvalidInvocation for an unusable invocation; it never prints anything, so
    mapping stays separate from presentation. The caller owns the usage output
    and the exit code.
    """
    if not argv:
        raise InvalidInvocation
    head, rest = argv[0], argv[1:]
    if head in ("-h", "--help"):
        raise HelpRequested
    if head == "adr":
        return _build_adr_command(rest)
    if head == "review":
        return _build_review_command(rest)
    if head == "edit":
        # `edit` takes no arguments: anything after the subcommand is ignored.
        # Editor resolution is environment-dependent (os.environ, shutil.which)
        # and belongs to the edit execution path, not to this pure mapping; a
        # signal keeps the subcommand -> execution-path decision in one place.
        raise EditRequested
    raise InvalidInvocation


def _resolve_editor() -> list[str]:
    # VISUAL/EDITOR values may carry arguments (`code --wait`), so they are
    # split like a shell command line. A malformed value (e.g. an unbalanced
    # quote) is skipped with a warning instead of crashing with a traceback.
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var)
        if not value:
            continue
        try:
            return shlex.split(value)
        except ValueError as exc:
            print(
                "warning: {} is malformed ({}); skipping it".format(var, exc),
                file=sys.stderr,
            )
    if shutil.which("nano"):
        return ["nano"]
    return ["vi"]


def _build_adr_command(rest: list[str]) -> list[str]:
    cmd = [RUN_PIPELINE, ADR_WORKFLOW]
    feature_parts: list[str] = []
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
            # so feature text like `-integration` is not mistaken for an input.
            passed.append(arg)
        else:
            feature_parts.append(arg)
        i += 1
    feature = " ".join(feature_parts)
    if not feature:
        raise InvalidInvocation
    cmd.append("-i")
    cmd.append("feature=" + feature)
    cmd.extend(passed)
    return cmd


def _build_review_command(rest: list[str]) -> list[str]:
    cmd = [RUN_PIPELINE, REVIEW_WORKFLOW]
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


class HelpRequested(Exception):
    """build_command saw `--help`/`-h`: print usage on stdout and exit 0."""


class InvalidInvocation(Exception):
    """build_command saw an unusable invocation: print usage on stderr and exit
    non-zero."""


class EditRequested(Exception):
    """build_command saw `edit`: open the installed config in the editor and
    re-apply it on exit (handled by the caller through _run_edit)."""


def print_usage(stream=None) -> None:
    """Print the usage text; defaults to stdout, pass sys.stderr for errors."""
    if stream is None:
        stream = sys.stdout
    print(USAGE, file=stream)


def _launch_editor(editor_cmd: list[str]) -> int | None:
    # The editor runs as a child process inheriting stdin/stdout so
    # full-screen editors keep working. Returns the editor's exit code, or
    # None when the editor could not be started (an error is printed then);
    # None is distinguishable from an editor that ran and exited with 1.
    try:
        return subprocess.run(editor_cmd, check=False).returncode
    except OSError as exc:
        print(
            "error: cannot start editor {}: {}".format(editor_cmd[0], exc),
            file=sys.stderr,
        )
        return None


def _apply_config() -> int:
    # Re-apply the (possibly edited) config through the repo installer: it
    # reloads and validates config.yml, re-renders every artifact and verifies
    # the result, without the install-time prerequisite/dependency checks or
    # the next-steps output. A config that fails validation surfaces here and
    # aborts `edit` with the installer's exit code.
    result = subprocess.run([sys.executable, INSTALL_PY, "--apply"], check=False)
    if result.returncode == 0:
        print("config applied - agents, scripts and workflows re-rendered")
    return result.returncode


def _run_edit() -> int:
    # `edit` takes no arguments; the config path is baked in at install time.
    # Resolve and run the editor, then re-apply the config whenever the editor
    # actually launched. The editor's own exit code does not gate the apply: a
    # user can save a valid edit and still close the editor non-zero (vim
    # :cq, ...), and `--apply` re-validates the config anyway, failing loudly
    # on an invalid edit. Only a failure to start the editor aborts.
    editor_cmd = _resolve_editor() + [CONFIG]
    if _launch_editor(editor_cmd) is None:
        return 1
    return _apply_config()


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
        return _run_edit()
    try:
        # os.execv replaces this process with run-pipeline.py, so its live
        # output, timestamps and exit code pass through unchanged; it returns
        # only when exec fails, which is why return 1 follows.
        os.execv(cmd[0], cmd)
    except OSError as exc:
        print("error: cannot run {}: {}".format(cmd[0], exc), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
