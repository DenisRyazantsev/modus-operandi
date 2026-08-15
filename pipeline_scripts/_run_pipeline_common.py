"""Shared constants and pure helpers of the run-pipeline.py wrapper.

Everything the class modules and the run_pipeline.py entry need in common
lives here: the terminal-status set, the display constants, the pure string
predicates (gate menu opener, feedback gate, truncation, rendering) and the
output primitives (timestamps, role labels, step markers). Each class module
imports only what it needs; run_pipeline.py re-exports the names for tests.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

# Step statuses the poller treats as finished. Anything else (running,
# pending, queued, unset) means the step is still in progress and must not be
# reported as a finished event.
TERMINAL_STATUSES = frozenset({"completed", "failed", "skipped"})

# Agent reasoning longer than this is truncated for the console display (the
# full text always stays in the .jsonl files).
MAX_LOG_TEXT_LEN = 100

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
    return bool(step_id) and FEEDBACK_GATE_MARKER in step_id


def truncate(text: str) -> str:
    """Shorten a displayed agent-log text to MAX_LOG_TEXT_LEN chars + "...".

    Agent reasoning events can be very long and flood the console; the full
    text always stays in the .jsonl files — this only shortens the console
    rendering. Pure function.
    """
    if len(text) > MAX_LOG_TEXT_LEN:
        return text[:MAX_LOG_TEXT_LEN] + "..."
    return text


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

    Only meaningful content is shown: `text` parts with a non-empty payload
    (the agents' actual work progression). Marker events (`step-start`,
    `step-finish`) and `text` parts with an empty payload carry no
    information and are dropped entirely. Lines that are not valid JSON at
    all (plain-text or malformed log lines) are the exception: they are
    shown truncated as-is rather than dropped, so raw agent output is never
    silently hidden. What stays visible from the logs is the agents'
    progression, while failures are reported by the failed step's own result
    and the final status block. Pure function: no file state, so the
    rendering rules are unit-testable without touching the log files.
    """
    line = line.strip()
    if not line:
        return role, ""
    try:
        event = json.loads(line)
    except Exception:
        return role, truncate(line)
    part = event.get("part") or {}
    if part.get("type") == "text" and part.get("text"):
        # text parts: print the payload (truncated for the console; the
        # .jsonl file keeps the full text).
        return role, truncate(part["text"])
    return role, ""


def print_step_result(step_id: str, result: dict) -> None:
    print_ts("--- step {} ({})".format(step_id, result.get("status")))
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
