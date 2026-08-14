#!/usr/bin/env python3
"""save_adr.py - release or sync an ADR for the adr-pipeline workflow.

Usage:
  save_adr.py save <state_dir> <task_id> <adr_dir> <run_agent>
  save_adr.py sync <state_dir> <task_id>

<task_id> may be empty: it is then resolved through the
<state_dir>/tasks/current symlink (see generate-task-id in the workflow).

save reads <state_dir>/tasks/<task_id>/adr.md, ensures its frontmatter has an
English 'slug', and writes <adr_dir>/ADR-<XXXX>-<slug>.md with the next free
number. If the slug is missing it asks the planner agent to add one (via the
agent_call.py helper) and only fails if the planner still refuses. The saved
path is written to <state_dir>/tasks/<task_id>/adr-saved.txt.

sync rewrites the saved ADR's heading to the number already in its filename
(used after the review loop amends adr.md).

The review-loop verdict gate lives in check_review.py; the scripts share
task_utils.py (task-dir resolution) and agent_call.py (agent invocation),
and the text rules (slug, numbering, heading rewrite) live in adr_utils.py.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from adr_utils import find_next_number, read_slug, rewrite_heading, sanitize_slug
from agent_call import ask_agent
from task_utils import resolve_task_dir


def _ask_planner_for_slug(adr_path: Path, run_agent: str, task_id: str) -> None:
    # The pipeline requires an English slug for the saved filename, but the
    # planner keeps forgetting to write it. Instead of failing the run, ask the
    # warm planner session to add the missing field; fail only if it still
    # refuses (handled by the caller). The invocation itself is delegated to
    # agent_call.py.
    prompt = (
        f"Read {adr_path}. Its YAML frontmatter (between the first two '---' lines) is "
        "missing the 'slug' field. Add it on its own line right after the opening "
        "'---': a short 2-3 word ENGLISH summary of the ADR in lowercase kebab-case "
        "(e.g. 'slug: prod-validation-splits'). Change nothing else."
    )
    ask_agent(run_agent, "planner", prompt, task_id)


def release_adr(task_dir: Path, adr_dir: Path, slug: str, text: str) -> Path:
    """Write the ADR to adr_dir under the next free number and record the path.

    Single job: release bookkeeping + file write. Idempotent per task
    (adr-saved.txt): a rerun of the same task keeps its number. A matching
    file without an own record belongs to a different task using the same
    slug — reusing it would silently overwrite that task's ADR on the next
    sync, so fail loudly instead.
    """
    saved_file = task_dir / "adr-saved.txt"
    own = saved_file.read_text(encoding="utf-8").strip() if saved_file.exists() else ""
    if own and Path(own).exists():
        # Rerun/resume of the same task: its ADR was already released — keep the
        # same number and record the path again (idempotency).
        saved_path = Path(own)
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
        saved_path = target
    saved_file.write_text(str(saved_path), encoding="utf-8")
    return saved_path


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

    release_adr(task_dir, Path(args.adr_dir), slug, text)


def cmd_sync(args: argparse.Namespace) -> None:
    task_dir = resolve_task_dir(args.state_dir, args.task_id)
    saved_file = task_dir / "adr-saved.txt"
    if not saved_file.exists():
        sys.exit("no adr-saved.txt")
    saved = saved_file.read_text(encoding="utf-8").strip()
    # The emptiness guard must run on the RAW string, before constructing the
    # Path: Path("") normalizes to "." (always truthy), so `not str(Path(...))`
    # never fires and an empty adr-saved.txt would fall through to the number
    # regex and exit with the cryptic "cannot extract ADR number from .".
    if not saved or not Path(saved).exists():
        print("warning: saved adr not found at " + str(saved))
        return
    target = Path(saved)
    m = re.search(r"ADR-(\d{4})-", str(target))
    if not m:
        sys.exit(
            f"error: cannot extract ADR number from {target}; "
            "expected ADR-<number>-<slug>.md"
        )
    num = m.group(1)
    text = (task_dir / "adr.md").read_text(encoding="utf-8")
    target.write_text(rewrite_heading(text, num), encoding="utf-8")
    print("adr synced: " + str(target))


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
    args = parser.parse_args(argv)
    if args.command == "save":
        cmd_save(args)
    else:
        cmd_sync(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
