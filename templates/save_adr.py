#!/usr/bin/env python3
"""save_adr.py - release or sync an ADR for the adr-pipeline workflow.

Usage:
  save_adr.py save <state_dir> <task_id> <adr_dir> <run_agent>
  save_adr.py sync <state_dir> <task_id>
  save_adr.py check-review <state_dir> <task_id> <kind>

<task_id> may be empty: it is then resolved through the
<state_dir>/tasks/current symlink (see generate-task-id in the workflow).

save reads <state_dir>/tasks/<task_id>/adr.md, ensures its frontmatter has an
English 'slug', and writes <adr_dir>/ADR-<XXXX>-<slug>.md with the next free
number. If the slug is missing it asks the planner agent to add one and only
fails if the planner still refuses. The saved path is written to
<state_dir>/tasks/<task_id>/adr-saved.txt.

sync rewrites the saved ADR's heading to the number already in its filename
(used after the review loop amends adr.md).
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^#\s*ADR(?:\s*-\s*\d+)?\s*:\s*(.+)$", re.M)
SLUG_MISSING_ERROR = (
    "error: adr.md frontmatter has no 'slug' field. The slug is a short 2-3 word "
    "ENGLISH summary in kebab-case (e.g. 'slug: prod-validation-splits') and "
    "becomes the saved filename"
)
SLUG_ASCII_ERROR = (
    "error: slug must contain ASCII letters (English), "
    "e.g. 'slug: prod-validation-splits'"
)


def read_slug(text: str) -> str | None:
    fm = text.split("---", 2)
    if len(fm) < 3:
        return None
    m = re.search(r"^slug:\s*(\S+)", fm[1], re.M)
    return m.group(1) if m else None


def sanitize_slug(raw: str) -> str:
    if not raw:
        raise ValueError(SLUG_ASCII_ERROR)
    # Collapse everything non-latin into '-' first so a fully non-ASCII slug
    # becomes empty and trips the check below instead of producing a weird
    # filename. A slug must contain at least one English letter.
    ascii_slug = re.sub(r"[^a-z0-9-]", "-", raw.lower()).strip("-")
    if not re.search(r"[a-z]", ascii_slug):
        raise ValueError(SLUG_ASCII_ERROR)
    # Truncate by whole words to 60 chars; a single oversized word is cut
    # itself rather than making the whole slug empty.
    words = [w[:60] for w in ascii_slug.split("-") if w]
    slug = ""
    for w in words:
        if len(slug) + len(w) + (1 if slug else 0) > 60:
            break
        slug = w if not slug else slug + "-" + w
    if not slug:
        raise ValueError("error: slug is empty after sanitization")
    return slug


def find_next_number(adr_dir: str) -> int:
    nums = [
        int(m.group(1))
        for m in (
            re.search(r"ADR-(\d{4})-", f)
            for f in glob.glob(os.path.join(adr_dir, "ADR-*.md"))
        )
        if m
    ]
    return max(nums) + 1 if nums else 1


def rewrite_heading(text: str, num: str) -> str:
    # Replaces "# ADR: <title>" or "# ADR-0003: <title>" with the canonical
    # "# ADR-<num>: <title>", keeping the title (usually Russian) intact.
    return re.sub(
        HEADING_RE,
        lambda m: f"# ADR-{num}: {m.group(1).strip()}",
        text,
        count=1,
    )


def resolve_task_dir(state_dir: str, task_id: str) -> Path:
    # task_id is usually generated at runtime by the generate-task-id step and
    # linked as <state_dir>/tasks/current -> tasks/<id>. When the workflow does
    # not know the id (empty string), resolve it through that symlink so all
    # steps agree on one id without templating it into every path.
    tasks = Path(state_dir) / "tasks"
    if task_id:
        return tasks / task_id
    current = tasks / "current"
    task_dir = current.resolve()
    if not task_dir.exists() or task_dir == current:
        sys.exit(
            f"error: {current} does not point to a task directory; run the "
            "pipeline from the start or pass an explicit task_id"
        )
    return task_dir


def _ask_planner_for_slug(adr_path: Path, run_agent: str, task_id: str) -> None:
    # The pipeline requires an English slug for the saved filename, but the
    # planner keeps forgetting to write it. Instead of failing the run, ask the
    # warm planner session to add the missing field; fail only if it still
    # refuses (handled by the caller).
    prompt = (
        f"Read {adr_path}. Its YAML frontmatter (between the first two '---' lines) is "
        "missing the 'slug' field. Add it on its own line right after the opening "
        "'---': a short 2-3 word ENGLISH summary of the ADR in lowercase kebab-case "
        "(e.g. 'slug: prod-validation-splits'). Change nothing else."
    )
    # list-form invocation (no shell=True) so a run-agent.sh path containing
    # spaces survives as a single argv element.
    subprocess.run(
        [run_agent, "planner", prompt, "--task", task_id], check=True
    )


def cmd_save(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    adr_path = task_dir / "adr.md"
    if not adr_path.exists():
        sys.exit(f"error: adr.md not found: {adr_path}")
    text = adr_path.read_text(encoding="utf-8")
    slug = read_slug(text)
    if slug is None:
        _ask_planner_for_slug(adr_path, args.run_agent, args.task_id)
        text = adr_path.read_text(encoding="utf-8")
        slug = read_slug(text)
        if slug is None:
            sys.exit(
                "error: adr.md still has no 'slug' field after the planner was "
                "asked to add it. Add a short 2-3 word ENGLISH summary in kebab-case "
                "(e.g. 'slug: prod-validation-splits') to the frontmatter manually "
                "and resume the run"
            )
    try:
        slug = sanitize_slug(slug)
    except ValueError as exc:
        sys.exit(str(exc) + "; fix the slug field in " + str(adr_path))

    adr_dir = Path(args.adr_dir)
    saved_file = task_dir / "adr-saved.txt"
    own = saved_file.read_text(encoding="utf-8").strip() if saved_file.exists() else ""
    if own and Path(own).exists():
        # Rerun/resume of the same task: its ADR was already released — keep the
        # same number and record the path again (idempotency).
        saved_path = own
        print("adr already saved: " + own)
    else:
        # No own release on record. A matching file can only belong to a
        # DIFFERENT task that happens to use the same slug — reusing it would
        # silently overwrite that task's ADR on the next sync. Fail loudly.
        colliding = sorted(adr_dir.glob(f"ADR-*-{slug}.md"))
        if colliding:
            sys.exit(
                f"error: an ADR with slug '{slug}' already exists as {colliding[0]} "
                f"but task '{task_dir.name}' has no saved ADR of its own. The slug is "
                f"used by another task; change it in adr.md (e.g. '{slug}-2') or "
                "remove the colliding file and resume the run"
            )
        num = find_next_number(str(adr_dir))
        name = f"ADR-{num:04d}-{slug}.md"
        target = adr_dir / name
        adr_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(rewrite_heading(text, f"{num:04d}"), encoding="utf-8")
        print("saved adr: " + str(target))
        saved_path = str(target)
    saved_file.write_text(saved_path, encoding="utf-8")


def cmd_sync(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    saved_file = task_dir / "adr-saved.txt"
    if not saved_file.exists():
        sys.exit("no adr-saved.txt")
    target = Path(saved_file.read_text(encoding="utf-8").strip())
    if not str(target) or not target.exists():
        print("warning: saved adr not found at " + str(target))
        return
    m = re.search(r"ADR-(\d{4})-", str(target))
    num = m.group(1) if m else "XXXX"
    text = (task_dir / "adr.md").read_text(encoding="utf-8")
    target.write_text(rewrite_heading(text, num), encoding="utf-8")
    print("adr synced: " + str(target))


def cmd_check_review(args: argparse.Namespace) -> None:
    # Shared verdict helper for the review loops (review, srp and comment kinds):
    # exits 0 when the LATEST <kind>-review-N.md starts with its PASS marker, 1
    # otherwise (mirrors the old shell chain `ls | sort -V | tail -1 && head -1 |
    # grep`). Always prints the latest file path (or nothing) so the pass-check
    # steps can report it.
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    # Files are named review-N.md, srp-review-N.md, bug-review-N.md and
    # comment-review-N.md.
    if args.kind == "srp":
        prefix = "srp-review"
        marker = "SRP: PASS"
    elif args.kind == "bugs":
        prefix = "bug-review"
        marker = "BUGS: PASS"
    elif args.kind == "comment":
        prefix = "comment-review"
        marker = "VERDICT: PASS"
    else:
        prefix = "review"
        marker = "VERDICT: PASS"
    files = sorted(task_dir.glob(f"{prefix}-*.md"))
    latest = files[-1] if files else None
    if latest is not None:
        print(str(latest))
    ok = latest is not None and latest.read_text(
        encoding="utf-8"
    ).splitlines()[0].strip() == marker
    sys.exit(0 if ok else 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_save = sub.add_parser("save")
    p_save.add_argument("state_dir")
    p_save.add_argument("task_id")
    p_save.add_argument("adr_dir")
    p_save.add_argument("run_agent")
    p_sync = sub.add_parser("sync")
    p_sync.add_argument("state_dir")
    p_sync.add_argument("task_id")
    p_check = sub.add_parser("check-review")
    p_check.add_argument("state_dir")
    p_check.add_argument("task_id")
    p_check.add_argument("kind", choices=("review", "srp", "bugs", "comment"))
    args = parser.parse_args(argv)
    if args.command == "save":
        cmd_save(args)
    elif args.command == "sync":
        cmd_sync(args)
    else:
        cmd_check_review(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
