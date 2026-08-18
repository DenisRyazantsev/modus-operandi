"""Shared constants and pure helpers of the run-pipeline.py wrapper.

Everything the class modules and the run_pipeline.py entry need in common
lives here: the terminal-status set, the display constants, the pure string
predicates (gate menu opener, feedback gate, rendering) and the output
primitives (timestamps, role labels, step markers). Each class module
imports only what it needs; run_pipeline.py re-exports the names for tests.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

# Step statuses the poller treats as finished. Anything else (running,
# pending, queued, unset) means the step is still in progress and must not be
# reported as a finished event.
TERMINAL_STATUSES = frozenset({"completed", "failed", "skipped"})

# Role names are fixed (planner/executor); the longest one sets the label
# width so text after "[role] " starts at the same column.
ROLE_LABEL_WIDTH = 8

# Substring that identifies the ADR revise feedback gate in a step id: the
# plain "adr-feedback-gate", or the loop-iteration form
# "adr-loop:adr-feedback-gate:N". The marker mirrors the step id chosen in
# the installed adr-pipeline.yml: current_step_id from state.json is the
# wrapper's only observation point for "which gate opened", so this is a
# deliberate cross-file coupling — renaming the step silently disables the
# editor path and the gate signals like a normal gate again.
FEEDBACK_GATE_MARKER = "feedback-gate"


def stamp() -> str:
    return time.strftime("%H:%M:%S")


def print_ts(text: str, prefix: str = "") -> None:
    text = text.rstrip()
    if not text:
        return
    for line in text.splitlines():
        print(f"[{stamp()}] {prefix}{line}", flush=True)


def run_id_from_text(text: str) -> str:
    m = re.search(r"Run ID: ([0-9a-f]{8})", text)
    if m:
        return m.group(1)
    # run-pipeline.py runs specify without --format json, so its stdout lines
    # are never JSON: there is no other run-id carrier on stdout.
    return ""


# specify-cli v0.16.x draws the human-gate menu with print(): the first line
# of the window starts with these characters (after stripping). This is the
# only observation point for "a gate menu is on screen" — the wrapper's own
# stdout pipe, the same one the menu is drawn into.
GATE_MENU_PREFIX = "┌─ Gate"


def is_gate_menu_opener(line: str) -> bool:
    """True when line is the first line of specify's human-gate menu window.

    Pure string predicate: while such a window is on screen, the wrapper
    buffers its own live output so the menu is not flooded. The menu window
    is drawn only for interactive gates on a TTY; `human_gates: false` and
    non-TTY runs never produce this line, so no suppression happens there.
    """
    return line.strip().startswith(GATE_MENU_PREFIX)


def is_feedback_gate(step_id: str | None) -> bool:
    """True when the step id identifies the ADR revise feedback gate.

    Matches the plain id ("adr-feedback-gate") and the loop-iteration form
    ("adr-loop:adr-feedback-gate:N") by substring. Pure predicate, so the
    gate recognition is unit-testable without a running workflow.
    """
    return step_id is not None and FEEDBACK_GATE_MARKER in step_id


def existing_run_ids(run_state_dir: Path) -> set[str]:
    """Names of the run directories already present under run_state_dir/runs.

    Snapshot these BEFORE the workflow process starts: a run directory that
    appears afterwards belongs to this invocation, and that is the only
    reliable way to recognize it. Guessing by newest mtime is not reliable
    here either — a resumed run keeps its original mtime, and a concurrent
    run could be newer.
    """
    runs_dir = run_state_dir / "workflows" / "runs"
    try:
        return {p.name for p in runs_dir.iterdir() if p.is_dir()}
    except OSError:
        return set()


def render_log_event(role: str, line: str) -> tuple[str, str]:
    """Map one raw log line to the (role, text) pair to display.

    Since ADR-0011 nothing is printed from the agent logs anymore: `text`
    and `reasoning` events are suppressed (the live status lines replace
    them) and raw non-JSON lines are no longer shown either. The function
    keeps its (role, text) contract for the tailer, which always receives an
    empty text; the parsed events are carried separately for the live lines.
    """
    return role, ""


def print_step_result(
    step_id: str,
    result: dict[str, Any],
    step_index: int | None = None,
    total_steps: int | None = None,
) -> None:
    """Print the finished-step marker and its captured output.

    `step_index` is the completed step's 0-based position among the
    workflow's top-level steps (resolved from the workflow file, ADR-0011);
    the marker is 1-based for humans, hence the `+1` at this only display
    site. Without a known index or a workflow file the marker omits the N/M
    part.
    """
    marker = "--- step {} ({})".format(step_id, result.get("status"))
    if step_index is not None and total_steps is not None:
        marker += f" [{step_index + 1}/{total_steps}]"
    print_ts(marker)
    out = result.get("output") or {}
    print_ts(out.get("stdout") or "", "    ")
    stderr = out.get("stderr") or ""
    if stderr:
        print_ts(stderr, "    [err] ")


def role_label(role: str) -> str:
    """Render the role inside brackets, left-aligned to the longest role
    name: "[planner ]" / "[executor]". Text after the label therefore starts
    at the same column for every role. Pure function.
    """
    return f"[{role.ljust(ROLE_LABEL_WIDTH)}]"


def print_log_event(role: str, text: str) -> None:
    print_ts(text, role_label(role) + " ")


def fmt_thousands(n: int | float) -> str:
    """Format a token count with space thousand separators: 321213 -> '321 213'."""
    return f"{int(n):,}".replace(",", " ")


def fmt_duration(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS (e.g. 6301 -> '01:45:01')."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def fmt_minutes(seconds: float) -> str:
    """Format elapsed seconds as whole minutes with an 'm' suffix.

    Standard rounding (e.g. 90 -> '2m'); a non-zero value under 30 seconds
    rounds up to '1m' so a stage never reads as zero minutes. `wall time` in
    the run statistics block keeps fmt_duration (HH:MM:SS) — this is only
    the latency table's compact form.
    """
    total = max(0, seconds)
    minutes = int(total / 60 + 0.5)
    if minutes == 0 and total > 0:
        minutes = 1
    return f"{minutes}m"


# The installed config dir, derived from this module's location (scripts/ ->
# opencode/ -> .config/, like CONFIG_PATH in config_invocation.py): used to
# resolve a bare workflow id to the installed workflow file.
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "spec-kit-llm-client"


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
            import yaml  # installed by the installer (deps.ensure_pyyaml)

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
    (e.g. `adr-loop:adr-gate:1`): the marker shows the position of the
    parent top-level step, so the suffix is stripped before the lookup.
    None when the step is unknown or no workflow file was read — the marker
    then omits the N/M part.
    """
    if not step_ids:
        return None
    base = step_id.split(":", 1)[0]
    try:
        return step_ids.index(base)
    except ValueError:
        return None
