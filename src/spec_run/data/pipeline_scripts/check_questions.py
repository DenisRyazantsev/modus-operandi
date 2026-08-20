#!/usr/bin/env python3
"""check_questions.py - exit condition of the executor-questions-loop.

Usage:
  check_questions.py check <state_dir> <task_id>

<task_id> may be empty: it is then resolved through the
<state_dir>/tasks/current symlink (see generate-task-id in the workflows).

check exits 0 when <task_dir>/questions.md exists and its first line is
exactly `QUESTIONS: NONE` (modulo surrounding whitespace — agent-written
markdown occasionally carries stray leading whitespace on the marker line,
and stripping accepts it so the loop does not burn a round on a formatting
artifact), 1 otherwise. The executor-questions step rewrites
questions.md every round (the remaining questions, or NONE when nothing is
left), so this is the loop's exit condition: the executor-questions-loop
repeats while the check fails, and the planner-answers branch answers the
current questions.md each round.
"""

from __future__ import annotations

import argparse
import sys

from task_utils import resolve_task_dir

NONE_MARKER = "QUESTIONS: NONE"


def cmd_check(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    questions = task_dir / "questions.md"
    if not questions.exists():
        sys.exit(1)
    lines = questions.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].strip() == NONE_MARKER:
        sys.exit(0)
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
