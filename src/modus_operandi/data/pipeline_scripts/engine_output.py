"""Engine stdout grammar: the predicates that filter specify's own output.

One responsibility: recognize the line shapes the specify engine prints on
stdout — the run-id line, the human-gate menu opener, the per-step
`▸` lines, the one-time run headers and the error/diagnostic lines — and
extract the run id from them. The wrapper (run_pipeline.py) uses these
predicates to decide what to echo and what to drop (ADR-0013), and the
resume message depends on the parsed run id.
"""

from __future__ import annotations

import re

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


def run_id_from_text(text: str) -> str:
    """The 8-hex run id of the engine's `Run ID:` line, or "" when absent."""
    m = re.search(r"Run ID: ([0-9a-f]{8})", text)
    if m:
        return m.group(1)
    # run-pipeline.py runs specify without --format json, so its stdout lines
    # are never JSON: there is no other run-id carrier on stdout.
    return ""


# specify-cli v0.16.x prints a `  ▸ [<step-id>] <type> ...` line at the start
# of every step (engine.on_step_start) and one-time headers at the beginning
# (`Running workflow:`/`Version:`) and end (`Status:`/`Run ID:`) of a run.
# The wrapper's own aligned step rows already show all of that, so under
# the strict "our format only" rule (ADR-0013) these lines are NOT echoed.
ENGINE_STEP_START_PREFIX = "▸ "
ENGINE_HEADER_PREFIXES = (
    "Running workflow:",
    "Version:",
    "Status:",
    "Run ID:",
)
# Engine errors and diagnostics are NOT dropped — they are re-emitted in the
# wrapper's own format, `[hh:mm:ss] [harness] <line as-is>` (ADR-0013), so
# nothing the user must see is lost.
ENGINE_ERROR_PREFIXES = (
    "Error:",
    "Workflow failed:",
    "Warning:",
)


def is_engine_step_start(line: str) -> bool:
    """True when line is specify's step-start line (`  ▸ [<step-id>] ...`).

    Pure string predicate (ADR-0013): the line announces a step that the
    wrapper's own aligned step rows (the pinned live lines and `[harness]`
    rows) already show, so it is filtered out of the echo.
    """
    return line.strip().startswith(ENGINE_STEP_START_PREFIX)


def is_engine_header(line: str) -> bool:
    """True when line is one of specify's one-time run header lines.

    `Running workflow:`/`Version:` at the start, `Status:`/`Run ID:` at the
    end of a run. The run id is parsed BEFORE this filtering
    (run_id_from_text), so dropping the line loses nothing — the resume
    message still works (ADR-0013). Pure string predicate.
    """
    stripped = line.strip()
    return any(stripped.startswith(prefix) for prefix in ENGINE_HEADER_PREFIXES)


def is_engine_error(line: str) -> bool:
    """True when line is an engine error or diagnostic line.

    `Error:`/`Workflow failed:`/`Warning:`. Such lines are not dropped: they
    are re-printed in the wrapper's own `[hh:mm:ss] [harness]` format
    (ADR-0013). Pure string predicate.
    """
    stripped = line.strip()
    return any(stripped.startswith(prefix) for prefix in ENGINE_ERROR_PREFIXES)
