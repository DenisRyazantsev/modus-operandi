#!/usr/bin/env python3
"""Shared helpers for the ADR/verdict scripts (save_adr.py, check_review.py)."""

from __future__ import annotations

import sys
from pathlib import Path


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
