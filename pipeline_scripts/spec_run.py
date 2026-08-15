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
from pathlib import Path

# The exceptions package (one class per file) ships next to this launcher —
# source: pipeline_scripts/exceptions/, installed: <bin dir>/exceptions/.
# `__file__` is the launcher itself, so its directory is the one place the
# package is guaranteed to be found, however the launcher is loaded (as an
# installed script, through exec, or by tests via importlib).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from exceptions import EditRequested, HelpRequested, InvalidInvocation


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
CONFIG = str(_config_dir() / "config.yml")

# The repo's install.py path, recorded by the installer for `spec-run edit`.
INSTALL_PATH_FILE = _config_dir() / "install-path.txt"

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


def _resolve_editor() -> list[str] | None:
    # VISUAL/EDITOR values may carry arguments (`code --wait`), so they are
    # split like a shell command line. A malformed value (e.g. an unbalanced
    # quote) is skipped with a warning, and a candidate whose binary is not
    # on PATH falls through to the next one (mirroring run_pipeline.py's
    # resolve_editor); None means no editor is available at all.
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
            f"error: cannot start editor {editor_cmd[0]}: {exc}",
            file=sys.stderr,
        )
        return None


def _install_py() -> str:
    """Return the recorded repo install.py path, or "" when not recorded.

    The installer writes the absolute path of the repo's install.py into
    install-path.txt; `spec-run edit` needs it to re-apply the config. The
    path cannot be derived from the launcher's own location (the repo clone
    may live anywhere), so a missing file means the installer metadata is
    gone (clone moved/deleted) and edit must fail with a readable error.
    """
    try:
        return INSTALL_PATH_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _apply_config() -> int:
    # Re-apply the (possibly edited) config through the repo installer: it
    # reloads and validates config.yml, re-renders every artifact and verifies
    # the result, without the install-time prerequisite/dependency checks or
    # the next-steps output. A config that fails validation surfaces here and
    # aborts `edit` with the installer's exit code.
    install_py = _install_py()
    if not install_py:
        print(
            f"error: cannot find the recorded install.py path ({INSTALL_PATH_FILE}); rerun "
            "install.py from the repo clone to record it",
            file=sys.stderr,
        )
        return 1
    result = subprocess.run([sys.executable, install_py, "--apply"], check=False)
    if result.returncode == 0:
        print("config applied - agents, scripts and workflows re-rendered")
    return result.returncode


def _run_edit() -> int:
    # `edit` takes no arguments; the config path is derived from the
    # launcher's location at import time. Resolve and run the editor, then
    # re-apply the config whenever the editor actually launched. The editor's
    # own exit code does not gate the apply: a user can save a valid edit and
    # still close the editor non-zero (vim :cq, ...), and `--apply`
    # re-validates the config anyway, failing loudly on an invalid edit. Only
    # a failure to start the editor aborts.
    editor_cmd = _resolve_editor()
    if editor_cmd is None:
        print(
            "error: no editor found; set VISUAL or EDITOR, or install nano/vi",
            file=sys.stderr,
        )
        return 1
    if _launch_editor(editor_cmd + [CONFIG]) is None:
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
        print(f"error: cannot run {cmd[0]}: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
