"""Display formatting: timestamps, the captured step output as `[harness]`
table rows, and number/format helpers.

One responsibility: the wrapper's console formatting — the `[hh:mm:ss]`
timestamp primitive, the captured stdout/stderr of finished steps
re-emitted as `[harness]` rows of the aligned log table (ADR-0016), and
the number/format helpers (thousands separators, HH:MM:SS durations,
compact minutes). Consumed by run_pipeline.py, live_monitor.py,
live_lines.py, table_format.py, run_statistics.py and latency_table.py;
nothing here reads or writes state.
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


def step_output_rows(result: dict[str, Any], layout: TableLayout) -> list[str]:
    """The captured stdout/stderr of a finished step as `[harness]` table rows.

    No step-marker line (ADR-0016): the pinned live line above already
    names the step, so the step column stays empty. `SESSION:` lines and
    empty lines are dropped; stderr lines keep the `[err] ` prefix. A
    malformed step result (a non-dict `output`, e.g. a torn state.json
    write) degrades to no rows: one broken step must not raise inside the
    monitor thread and silently kill the live status.
    """
    rows: list[str] = []
    out = result.get("output")
    out = out if isinstance(out, dict) else {}
    for line in (out.get("stdout") or "").splitlines():
        line = line.rstrip()
        if not line or line.startswith(SESSION_PREFIX):
            continue
        rows.append(layout.row("harness", " ", layout.empty_step(), line))
    for line in (out.get("stderr") or "").splitlines():
        line = line.rstrip()
        if not line:
            continue
        rows.append(layout.row("harness", " ", layout.empty_step(), f"[err] {line}"))
    return rows
