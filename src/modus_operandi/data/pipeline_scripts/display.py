"""Display formatting: timestamps, step markers and number/format helpers.

One responsibility: the wrapper's console formatting — the `[hh:mm:ss]`
timestamp primitive, the finished-step marker with its captured output,
and the number/format helpers (thousands separators, HH:MM:SS durations,
compact minutes). Consumed by run_pipeline.py, run_statistics.py,
latency_table.py and buffered_emitter.py; nothing here reads or writes
state.
"""

from __future__ import annotations

import time
from typing import Any


def stamp() -> str:
    return time.strftime("%H:%M:%S")


def print_ts(text: str, prefix: str = "") -> None:
    text = text.rstrip()
    if not text:
        return
    for line in text.splitlines():
        print(f"[{stamp()}] {prefix}{line}", flush=True)


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
