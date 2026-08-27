"""Display formatting: timestamps, the captured step output as `[harness]`
table rows, and number/format helpers.

One responsibility: the wrapper's console formatting — the `[hh:mm:ss]`
timestamp primitive, the captured stdout/stderr of finished steps
re-emitted as `[harness]` rows of the aligned log table (ADR-0016) or as
document blocks (ADR-0021 — the content between marker lines prints as a
free-form block from the left margin), and the number/format helpers
(thousands separators, HH:MM:SS durations, compact minutes). Consumed by
run_pipeline.py, live_monitor.py, live_lines.py, table_format.py,
run_statistics.py and latency_table.py; nothing here reads or writes
state.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from table_format import TableLayout


def stamp() -> str:
    return time.strftime("%H:%M:%S")


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


# Captured step output whose id is recoverable from files: not printed.
SESSION_PREFIX = "SESSION:"


# The document-block protocol (ADR-0021): a step that wants its captured
# stdout shown as a free-form block (not as per-line table rows) wraps the
# content in these marker lines. The FIRST stdout line must be the begin
# marker `MO-BLOCK-START:<label>`; the first later line equal to BLOCK_END
# closes the block. Matching is whole-line after rstrip; a begin marker
# without a matching end marker (torn output) falls back to the per-line
# table rows. The marker strings are chosen to be distinctive (precedent:
# GHA ::group::, PGP/PEM armor) and are consumed by the wrapper, never
# printed.
BLOCK_START_PREFIX = "MO-BLOCK-START:"
BLOCK_END = "MO-BLOCK-END"


def _stdout_block(stdout: str) -> tuple[str, list[str]] | None:
    """The (label, lines) of a document block in captured stdout, or None.

    The block protocol (ADR-0021): the first stdout line must be the begin
    marker `MO-BLOCK-START:<label>` and a later line must equal BLOCK_END;
    the label may be empty. Returns the enclosed lines verbatim (each
    rstripped, empty lines kept). A begin marker without a matching end
    marker returns None: the caller falls back to the per-line table rows
    and never raises. A stdout that does not start with the marker also
    returns None (ordinary step output).
    """
    lines = stdout.splitlines()
    if not lines:
        return None
    first = lines[0].rstrip()
    if not first.startswith(BLOCK_START_PREFIX):
        return None
    label = first[len(BLOCK_START_PREFIX) :].strip()
    for index in range(1, len(lines)):
        if lines[index].rstrip() == BLOCK_END:
            return label, [line.rstrip() for line in lines[1:index]]
    return None


def step_output_rows(result: dict[str, Any], layout: TableLayout) -> list[str]:
    """The captured stdout/stderr of a finished step as `[harness]` table rows.

    No step-marker line (ADR-0016): the pinned live line above already
    names the step, so the step column stays empty. `SESSION:` lines and
    empty lines are dropped; stderr lines keep the `[err] ` prefix. A
    marker-wrapped stdout (ADR-0021) renders as one announcement row and
    then the document verbatim from the left margin — the `SESSION:`/
    empty-line filtering and the table row formatting apply to the
    fallback (non-block) path only. A malformed step result (a non-dict
    `output`, e.g. a torn state.json write) degrades to no rows: one
    broken step must not raise inside the monitor thread and silently
    kill the live status.
    """
    rows: list[str] = []
    out = result.get("output")
    out = out if isinstance(out, dict) else {}
    # The same hardening as the `output` container: the engine writes
    # strings, but a torn or hand-edited state.json can carry anything —
    # a non-str field must degrade to no lines, not raise inside the
    # monitor thread and silently kill the live status.
    stdout = out.get("stdout")
    stdout = stdout if isinstance(stdout, str) else ""
    stderr = out.get("stderr")
    stderr = stderr if isinstance(stderr, str) else ""
    block = _stdout_block(stdout)
    if block is not None:
        # ADR-0021: one announcement row (table format, empty step column,
        # label + colon), then the document verbatim from the left margin;
        # the marker lines are consumed and never printed.
        label, lines = block
        tail = f"{label}:" if label else ""
        rows.append(layout.row("harness", " ", layout.empty_step(), tail))
        rows.extend(lines)
    else:
        for line in stdout.splitlines():
            line = line.rstrip()
            if not line or line.startswith(SESSION_PREFIX):
                continue
            rows.append(layout.row("harness", " ", layout.empty_step(), line))
    for line in stderr.splitlines():
        line = line.rstrip()
        if not line:
            continue
        rows.append(layout.row("harness", " ", layout.empty_step(), f"[err] {line}"))
    return rows
