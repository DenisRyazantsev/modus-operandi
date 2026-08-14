#!/usr/bin/env python3
"""check_review.py - verdict gate for the review loops of both workflows.

Usage:
  check_review.py check-review <state_dir> <task_id> <kind>

<task_id> may be empty: it is then resolved through the
<state_dir>/tasks/current symlink (see generate-task-id in the workflows).

kind is one of review|srp|bugs|comment. Exits 0 when the LATEST
<kind>-review-N.md starts with its PASS marker, 1 otherwise (mirrors the old
shell chain `ls | sort -V | tail -1 && head -1 | grep`). Always prints the
latest file path (or nothing) so the pass-check steps can report it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from task_utils import resolve_task_dir

# kind -> (file prefix, PASS marker). Files are named review-N.md,
# srp-review-N.md, bug-review-N.md and comment-review-N.md.
KINDS: dict[str, tuple[str, str]] = {
    "srp": ("srp-review", "SRP: PASS"),
    "bugs": ("bug-review", "BUGS: PASS"),
    "comment": ("comment-review", "VERDICT: PASS"),
    "review": ("review", "VERDICT: PASS"),
}

SUFFIX_RE = re.compile(r"-(\d+)\.md$")


def _file_number(path: Path) -> int:
    m = SUFFIX_RE.search(path.name)
    assert m is not None  # defensive; callers filter by SUFFIX_RE first
    return int(m.group(1))


def cmd_check_review(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    prefix, marker = KINDS[args.kind]
    # Sort by the numeric suffix (version order, mirroring the old
    # `ls | sort -V | tail -1` chain): lexicographic order would pick
    # review-9.md over review-10.md once N reaches 10. Stray files that match
    # the glob but have no numeric suffix (e.g. review-notes.md) are ignored.
    files = sorted(
        (p for p in task_dir.glob(f"{prefix}-*.md") if SUFFIX_RE.search(p.name)),
        key=_file_number,
    )
    latest = files[-1] if files else None
    if latest is not None:
        print(str(latest))
    ok = False
    if latest is not None:
        lines = latest.read_text(encoding="utf-8").splitlines()
        ok = bool(lines) and lines[0].strip() == marker
    sys.exit(0 if ok else 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check-review")
    p_check.add_argument("state_dir")
    p_check.add_argument("task_id")
    p_check.add_argument("kind", choices=tuple(KINDS))
    args = parser.parse_args(argv)
    cmd_check_review(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
