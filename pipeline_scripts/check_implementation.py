#!/usr/bin/env python3
"""check_implementation.py - guard that the implement step actually changed the repo.

Usage:
  check_implementation.py check <adr_dir>

Verifies the working tree contains changes attributable to the executor's
implementation work:

  1. tracked files modified (git diff HEAD, staged or not), or
  2. new untracked files that are not gitignored (git ls-files --others
     --exclude-standard).

Files that the pipeline itself writes outside the executor's control are
excluded: the saved ADR (<adr_dir>/ADR-*.md) is created by save-adr before the
implement step, so without the exclusion an empty implementation would always
"pass" because the fresh ADR file is untracked.

Exits 0 when changes are present, 1 otherwise — no changes and git errors
alike (a git error is reported in the printed summary).
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run git with the given arguments, capturing output without raising."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def has_changes(adr_dir: str) -> tuple[bool, str]:
    """Return (changes_present, summary) for the current working tree."""
    summary: list[str] = []
    diff = run_git(["diff", "--quiet", "HEAD"])
    if diff.returncode not in (0, 1):
        return False, f"git diff failed: {(diff.stderr or diff.stdout).strip()}"
    if diff.returncode == 1:
        summary.append("tracked files modified")
    untracked = run_git(["ls-files", "--others", "--exclude-standard"])
    if untracked.returncode != 0:
        return False, f"git ls-files failed: {(untracked.stderr or untracked.stdout).strip()}"
    # The pipeline's own saved ADR (written by save-adr before implement) is
    # untracked but is not executor work.
    adr_prefix = adr_dir.rstrip("/") + "/ADR-"
    new_files = [line for line in untracked.stdout.splitlines() if not line.startswith(adr_prefix)]
    if new_files:
        summary.append(f"{len(new_files)} new file(s)")
    if not summary:
        return False, "no changes"
    return True, "; ".join(summary)


def cmd_check(args: argparse.Namespace) -> None:
    changes, summary = has_changes(args.adr_dir)
    print("implementation check: " + summary)
    sys.exit(0 if changes else 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("adr_dir")
    args = parser.parse_args(argv)
    cmd_check(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
