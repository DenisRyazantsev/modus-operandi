"""Workflow-file introspection: the installed config dir and the step-id lists.

One responsibility: read the workflow files the wrapper is running — the
installed config dir derived from this module's location, the ordered
top-level step ids of a workflow source (path or bare id) and the
completed step's own position among them. The N/M progress markers of the
wrapper depend on this; any missing/unreadable input degrades to None so
the run never fails here.
"""

from __future__ import annotations

from pathlib import Path

# The installed config dir, derived from this module's location (scripts/ ->
# opencode/ -> .config/, like CONFIG_PATH in config_invocation.py): used to
# resolve a bare workflow id to the installed workflow file.
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "modus-operandi"


def workflow_step_ids(source: str) -> list[str] | None:
    """The ordered top-level step ids of the workflow file, or None.

    The wrapper's argv[0] is either a path to the workflow file (also a
    relative path from cwd) or a bare id; a bare id is resolved against the
    installed config dir and the cwd. Any missing file or unparseable YAML
    degrades to None — the N/M progress is then omitted without failing the
    run (ADR-0011). The id list (not just the count) lets the step markers
    show the completed step's own position instead of the engine's
    `current_step_index`, which has usually already advanced to the next
    step when the result is polled.
    """
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
            import yaml  # pyproject.toml declares pyyaml as a package dependency

            data = yaml.safe_load(text)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            ids = [
                step["id"]
                for step in data["steps"]
                if isinstance(step, dict) and isinstance(step.get("id"), str)
            ]
            if ids:
                return ids
    return None


def step_marker_index(step_id: str, step_ids: list[str] | None) -> int | None:
    """The 0-based index of a completed step among the top-level steps.

    The engine writes loop-iteration results with a suffixed id
    (e.g. `motivation-loop:motivation-gate:1` in task-pipeline.yml): the
    marker shows the position of the parent top-level step, so the suffix
    is stripped before the lookup. None when the step is unknown or no
    workflow file was read — the marker then omits the N/M part.
    """
    if not step_ids:
        return None
    base = step_id.split(":", 1)[0]
    try:
        return step_ids.index(base)
    except ValueError:
        return None
