#!/usr/bin/env python3
"""save_adr.py - release the final ADR for the task-pipeline workflow.

Usage:
  save_adr.py save <state_dir> <task_id> <adr_dir> <run_agent>

<task_id> may be empty: it is then resolved through the
<state_dir>/tasks/current symlink (see generate-task-id in the workflow).

save reads <state_dir>/tasks/<task_id>/adr.md, ensures its frontmatter has an
English 'slug', and writes <adr_dir>/ADR-<XXXX>-<slug>.md with the next free
number. If the slug is missing it asks the planner agent to add one (via the
agent_call.py helper) and only fails if the planner still refuses. The saved
path is written to <state_dir>/tasks/<task_id>/adr-saved.txt. The released
file is the final version of the ADR: save runs at the end of the pipeline,
after the planner has incorporated every agreed clarification.

The review-loop verdict gate lives in check_review.py; the scripts share
task_utils.py (task-dir resolution) and agent_call.py (agent invocation),
and the text rules (slug, numbering, heading rewrite) live in adr_utils.py.
"""

from __future__ import annotations

import argparse
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
    file without an own record belongs to a different task that already took
    the same slug — a second record with the same slug would make the two
    ADRs indistinguishable, so fail loudly instead.
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
        # DIFFERENT task that already took the same slug — releasing again
        # would publish a second ADR with the same slug and make the two
        # records indistinguishable. Fail loudly.
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_save = sub.add_parser("save")
    p_save.add_argument("state_dir")
    p_save.add_argument("task_id")
    p_save.add_argument("adr_dir")
    p_save.add_argument("run_agent")
    args = parser.parse_args(argv)
    if args.command == "save":
        cmd_save(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
