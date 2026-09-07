#!/usr/bin/env python3
"""check_review.py - verdict gate for the review loops of both workflows.

Usage:
  check_review.py check-review <state_dir> <task_id> <kind>
  check_review.py pending <state_dir> <task_id>
  check_review.py merge <state_dir> <task_id>

<task_id> may be empty: it is then resolved through the
<state_dir>/tasks/current symlink (see generate-task-id in the workflows).

kind is one of review|srp|bugs|comment|tests. check-review exits 0 when the LATEST
<kind>-review-N.md starts with its PASS marker, 1 otherwise (mirrors the old
shell chain `ls | sort -V | tail -1 && head -1 | grep`). Always prints the
latest file path (or nothing) so the review steps can compute the next
report number.

pending prints a JSON array of the kinds whose latest report does NOT start
with its PASS marker (all five kinds when no reports exist yet); it always
exits 0. The parallel review fan-out step uses it as its `items`.

merge deterministically concatenates the five LATEST reports into
<task_dir>/review-report.md (one section per kind, no synthesis) — the single
input document for the executor's fix-all step. It exits 0 only when all five
latest reports carry their PASS markers, 1 otherwise (a FIX verdict is an
expected outcome, so callers run it with continue_on_error).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from task_utils import resolve_task_dir

# kind -> (file prefix, PASS marker). Files are named review-N.md,
# srp-review-N.md, bug-review-N.md, comment-review-N.md and tests-review-N.md.
KINDS: dict[str, tuple[str, str]] = {
    "srp": ("srp-review", "SRP: PASS"),
    "bugs": ("bug-review", "BUGS: PASS"),
    "comment": ("comment-review", "VERDICT: PASS"),
    "review": ("review", "VERDICT: PASS"),
    "tests": ("tests-review", "TESTS: PASS"),
}

# Deterministic order of the parallel checks: the order of the fan-out items
# on the first iteration and of the merged review-report.md sections.
KIND_ORDER: tuple[str, ...] = ("srp", "bugs", "review", "comment", "tests")

# Kind -> reviewer role convention (ADR-0017): the reviewer role name of a
# kind is `reviewer-<kind>` (reviewer-srp, reviewer-bugs, reviewer-review,
# reviewer-comment, reviewer-tests). KIND_ORDER is the single source of truth
# for the kinds:
# the Python consumers derive the reviewer names / fan-out labels from it
# (table_format.py ROLE_WIDTH, agent_log_tailer.py's reviewer-log regex,
# run_statistics.py's kind loop, latency_table.py's positional fan-out label
# mapping). The shell consumers (review-check.sh's case, run-agent.sh's
# REVIEWER_ROLE_RE) and the install-side lists (render.py REVIEWER_KINDS,
# paths.py / verify.py / uninstall.py) carry their own copies — a new kind
# must be added to every consumer above in lockstep.

# Section headings of the merged review-report.md, one per kind.
KIND_TITLES: dict[str, str] = {
    "srp": "SRP review",
    "bugs": "Bugs review",
    "review": "General review",
    "comment": "Comment (readability) review",
    "tests": "Tests review",
}

SUFFIX_RE = re.compile(r"-(\d+)\.md$")


def _file_number(path: Path) -> int:
    m = SUFFIX_RE.search(path.name)
    assert m is not None  # defensive; callers filter by SUFFIX_RE first
    return int(m.group(1))


def _latest_report(task_dir: Path, prefix: str) -> Path | None:
    # Sort by the numeric suffix (version order, mirroring the old
    # `ls | sort -V | tail -1` chain): lexicographic order would pick
    # review-9.md over review-10.md once N reaches 10. Stray files that match
    # the glob but have no numeric suffix (e.g. review-notes.md) are ignored.
    files = sorted(
        (p for p in task_dir.glob(f"{prefix}-*.md") if SUFFIX_RE.search(p.name)),
        key=_file_number,
    )
    return files[-1] if files else None


def _is_pass(latest: Path | None, marker: str) -> bool:
    if latest is None:
        return False
    lines = latest.read_text(encoding="utf-8").splitlines()
    return bool(lines) and lines[0].strip() == marker


def cmd_check_review(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    prefix, marker = KINDS[args.kind]
    latest = _latest_report(task_dir, prefix)
    if latest is not None:
        print(str(latest))
    sys.exit(0 if _is_pass(latest, marker) else 1)


def cmd_pending(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    failed = [
        kind
        for kind in KIND_ORDER
        if not _is_pass(_latest_report(task_dir, KINDS[kind][0]), KINDS[kind][1])
    ]
    print(json.dumps(failed))
    sys.exit(0)


def cmd_merge(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    sections: list[str] = []
    all_pass = True
    for kind in KIND_ORDER:
        prefix, marker = KINDS[kind]
        latest = _latest_report(task_dir, prefix)
        if not _is_pass(latest, marker):
            all_pass = False
        body = latest.read_text(encoding="utf-8").rstrip() if latest is not None else "(no report)"
        sections.append(f"## {KIND_TITLES[kind]}\n\n{body}")
    (task_dir / "review-report.md").write_text(
        "\n\n---\n\n".join(sections) + "\n", encoding="utf-8"
    )
    sys.exit(0 if all_pass else 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check-review")
    p_check.add_argument("state_dir")
    p_check.add_argument("task_id")
    p_check.add_argument("kind", choices=tuple(KINDS))
    p_pending = sub.add_parser("pending")
    p_pending.add_argument("state_dir")
    p_pending.add_argument("task_id")
    p_merge = sub.add_parser("merge")
    p_merge.add_argument("state_dir")
    p_merge.add_argument("task_id")
    args = parser.parse_args(argv)
    if args.command == "check-review":
        cmd_check_review(args)
    elif args.command == "pending":
        cmd_pending(args)
    else:
        cmd_merge(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
