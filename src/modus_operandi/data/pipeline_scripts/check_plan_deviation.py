#!/usr/bin/env python3
"""check_plan_deviation.py - exit condition of the plan-deviation-loop.

Usage:
  check_plan_deviation.py check <state_dir> <task_id>

<task_id> may be empty: it is then resolved through the
<state_dir>/tasks/current symlink (see generate-task-id in the workflow).

check exits 0 when <task_dir>/plan-deviation.md does NOT exist, 1 when it
exists. The planner-agreement step deletes the file after resolving it, so
this is the loop's exit condition (mirrors check_questions.py).
"""

from __future__ import annotations

import argparse
import sys

from task_utils import resolve_task_dir


def cmd_check(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    if (task_dir / "plan-deviation.md").exists():
        sys.exit(1)
    sys.exit(0)


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
