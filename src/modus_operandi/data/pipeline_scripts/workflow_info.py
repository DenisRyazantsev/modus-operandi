"""Workflow-file introspection: the installed config dir and the step-id lists.

One responsibility: read the workflow files the wrapper is running — the
installed config dir derived from this module's location, the ordered
top-level step ids of a workflow source (path or bare id) and every step
id of the workflow file (nested included) for the aligned step column of
the log rows. Any missing/unreadable input degrades to None so the run
never fails here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# The installed config dir, derived from this module's location (scripts/ ->
# opencode/ -> .config/, like CONFIG_PATH in config_invocation.py): used to
# resolve a bare workflow id to the installed workflow file.
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "modus-operandi"


def _workflow_document(source: str) -> dict[str, Any] | None:
    """The parsed workflow document, or None when unreadable/unparseable."""
    candidates: list[Path] = []
    if Path(source).is_file():
        candidates.append(Path(source))
    else:
        candidates.append(CONFIG_DIR / f"{source}.yml")
        candidates.append(Path.cwd() / f"{source}.yml")
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            return data
    return None


def _collect_step_ids(node: object) -> list[str]:
    """Every step id under a workflow node, nested steps included."""
    if not isinstance(node, dict):
        return []
    ids: list[str] = []
    if isinstance(node.get("id"), str):
        ids.append(node["id"])
    for key in ("steps", "then", "else"):
        children = node.get(key)
        if isinstance(children, list):
            for child in children:
                ids.extend(_collect_step_ids(child))
    inner = node.get("step")  # fan-out: the step template
    if isinstance(inner, dict):
        ids.extend(_collect_step_ids(inner))
    return ids


def workflow_step_ids(source: str) -> list[str] | None:
    """The ordered top-level step ids of the workflow file, or None.

    The wrapper's argv[0] is either a path to the workflow file (also a
    relative path from cwd) or a bare id; a bare id is resolved against the
    installed config dir and the cwd. Any missing file or unparseable YAML
    degrades to None — the run never fails here.
    """
    doc = _workflow_document(source)
    if doc is None:
        return None
    ids = [
        step["id"]
        for step in doc["steps"]
        if isinstance(step, dict) and isinstance(step.get("id"), str)
    ]
    return ids or None


def workflow_all_step_ids(source: str) -> list[str] | None:
    """Every step id of the workflow file (nested included), or None."""
    doc = _workflow_document(source)
    if doc is None:
        return None
    ids = _collect_step_ids(doc)
    return ids or None
