#!/usr/bin/env python3
"""spec-run - global launcher for the spec-kit-llm-client pipelines.

Installed once into ~/.local/bin by install.py and callable from any project
directory, without `specify init` or `--register`. It delegates to the
installed run-pipeline.py wrapper with the absolute workflow path, so runs
keep the timestamps, live step output, run statistics and the victory sound.

Usage:
  spec-run adr "feature description" [-i key=value ...]
  spec-run review [--branch-diff]
  spec-run --help | -h

Examples:
  spec-run adr "build a kanban board"
  spec-run adr "build a kanban board" -i task_id=kanban
  spec-run review
  spec-run review --branch-diff
"""

from __future__ import annotations

import os
import sys

# Absolute paths baked in at install time; rerun install.py after moving
# ~/.config/spec-kit-llm-client or ~/.config/opencode.
RUN_PIPELINE = "${run_pipeline}"
ADR_WORKFLOW = "${adr_workflow}"
REVIEW_WORKFLOW = "${review_workflow}"

USAGE = """Usage: spec-run <subcommand> [args]

  spec-run adr "feature description" [-i key=value ...]
      Run the full ADR pipeline for the feature (ADR -> implementation ->
      review). All non-flag arguments after `adr` are joined into the feature
      input; -i key=value arguments are passed through to the workflow.

  spec-run review [--branch-diff] [-i key=value ...]
      Review the project code (default: the whole codebase). With --branch-diff
      only the changes between the current branch and the default branch.

  spec-run --help | -h
      Print this help and exit 0.

Examples:
  spec-run adr "build a kanban board"
  spec-run adr "build a kanban board" -i task_id=kanban
  spec-run review
  spec-run review --branch-diff
"""


def build_command(argv: list[str]) -> list[str]:
    """Map spec-run argv to the command to execute (pure dispatch).

    Raises HelpRequested for `--help`/`-h` and InvalidInvocation for an
    unusable invocation; it never prints anything, so mapping stays separate
    from presentation. The caller owns the usage output and the exit code.
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
    raise InvalidInvocation


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


def print_usage(stream=None) -> None:
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
