#!/usr/bin/env python3
"""check_summary.py - warning-only guard for the final executor summary.

Usage:
  check_summary.py check <state_dir> <task_id>

<task_id> may be empty: it is then resolved through the
<state_dir>/tasks/current symlink (see generate-task-id in the workflows).

check exits 0 when <task_dir>/summary.md exists, 1 when it does not. A
missing summary is unexpected behavior - the executor was asked to write it
in the final step (ADR-0019) - so the check prints a warning to stderr; the
workflow step carries continue_on_error, so the run never fails because of
the summary.
"""

from __future__ import annotations

import argparse
import sys

from task_utils import resolve_task_dir


def cmd_check(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    if (task_dir / "summary.md").exists():
        sys.exit(0)
    print(
        "WARNING: the executor did not write summary.md (unexpected behavior, "
        "ADR-0019); the final summary is missing, the run result is unaffected",
        file=sys.stderr,
    )
    sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("state_dir")
    p_check.add_argument("task_id")
    args = parser.parse_args(argv)
    if args.command == "check":
        cmd_check(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
