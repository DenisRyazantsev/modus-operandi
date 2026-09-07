"""Per-stage latency table of the run-pipeline.py wrapper (ADR-0009).

One responsibility: measure where the pipeline's wall-clock time went. The
wrapper reads the specify engine's run log (.specify/workflows/runs/<run_id>/
log.jsonl) for the per-step start/stop timestamps (step_results carry no
timestamps), splits each stage's duration into agent-call time (span of the
per-role agent-log event timestamps inside the stage window) and shell
overhead, and prints the `=== latency by stage ===` block — including the
parallel-checks detail for the review fan-out. Missing data always degrades
to an empty block or zeros — the wrapper never fails here.
"""

from __future__ import annotations

import bisect
import datetime
import json
import re
from pathlib import Path
from typing import Any

from check_review import KIND_ORDER
from display import fmt_minutes

# The engine's nested fan-out item step ids are review-fan:check:<index> on
# retry-loop iteration 1 and review-fix-loop:review-fan:<iter>:check:<index>
# on later iterations (the loop, fan-out and template ids are fixed in both
# workflow sources). Group 1 is the loop iteration (None on iteration 1),
# group 2 the item index.
_FAN_OUT_ITEM_RE = re.compile(
    r"^(?:review-fix-loop:review-fan:(\d+):)?(?:review-fan:)?check:(\d+)$"
)


def _epoch(iso: str) -> float:
    """Parse the engine's ISO-8601 log.jsonl timestamp into epoch seconds."""
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def collect_latency(run_dir: Path | None) -> list[dict[str, Any]]:
    """Parse the run's log.jsonl into per-step (id, start, end, status) records.

    The engine persists step start/stop with timestamps in
    .specify/workflows/runs/<run_id>/log.jsonl (`step_started` /
    `step_completed` events, nested steps included) — step_results carry no
    timestamps, so this file is the wrapper's observation point. Records are
    returned in first-started order; any missing/unreadable data yields an
    empty list and the caller degrades to an empty table.
    """
    if run_dir is None:
        return []
    try:
        lines = (run_dir / "log.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    starts: dict[str, float] = {}
    records: dict[str, dict[str, Any]] = {}
    for line in lines:
        try:
            event = json.loads(line)
        except Exception:
            continue
        step_id = event.get("step_id")
        ts = _epoch(event.get("timestamp") or "")
        if event.get("event") == "step_started" and isinstance(step_id, str) and ts:
            starts[step_id] = ts
        elif event.get("event") == "step_completed" and isinstance(step_id, str) and ts:
            records[step_id] = {
                "id": step_id,
                "start": starts.get(step_id, ts),
                "end": ts,
                "status": event.get("status", ""),
            }
    return sorted(records.values(), key=lambda r: r["start"])


def _agent_timestamps(state_dir: Path) -> list[float]:
    """All agent-log event timestamps (epoch seconds), sorted.

    The per-role agent logs (.jsonl under <state_dir>/logs) carry
    `"timestamp": <epoch-ms>` on every event; the parallel-check forks write
    per-invocation log files that are picked up by the same glob. Any
    unreadable file is skipped — the breakdown degrades to zeros.
    """
    timestamps: list[float] = []
    logs_dir = state_dir / "logs"
    if not logs_dir.is_dir():
        return timestamps
    for path in sorted(logs_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            m = re.search(r'"timestamp":\s*(\d+)', line)
            if m:
                timestamps.append(int(m.group(1)) / 1000.0)
    timestamps.sort()
    return timestamps


def _span_within(timestamps: list[float], start: float, end: float) -> float:
    """Seconds spanned by the agent-log timestamps inside [start, end]."""
    if not timestamps or end <= start:
        return 0.0
    i = bisect.bisect_left(timestamps, start)
    j = bisect.bisect_right(timestamps, end)
    if i >= j:
        return 0.0
    return timestamps[j - 1] - timestamps[i]


def _fan_out_kind(run_dir: Path, step_id: str, idx: int) -> str | None:
    """Best-effort kind label of a fan-out item step, or None.

    Iteration 1 of the retry loop always fans out over every kind in the
    deterministic order of KIND_ORDER (imported above), so the label is
    positional. On later iterations (review-fix-loop:review-fan:<iter>:
    check:<idx>) the per-iteration pending step's stdout (a JSON list of the
    re-reviewed kinds) is read from the run's final state.json. Any failure
    (no state file, unparseable output) degrades to None — the raw step id
    is shown.
    """
    kinds = KIND_ORDER
    m = re.match(r"^review-fix-loop:review-fan:(\d+):", step_id)
    if m is None:
        return kinds[idx] if idx < len(kinds) else None
    try:
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        pending = state.get("step_results", {}).get(
            f"review-fix-loop:pending-kinds:{m.group(1)}", {}
        )
        stdout = (pending.get("output") or {}).get("stdout", "")
        kinds_list = json.loads(stdout)
    except Exception:
        return None
    if not isinstance(kinds_list, list):
        return None
    return kinds_list[idx] if idx < len(kinds_list) else None


def print_latency_table(state_dir: Path, run_dir: Path | None) -> None:
    """Print the `=== latency by stage ===` block, or nothing when no data.

    One row per stage (step id -> duration) with the agent-call vs
    shell-overhead breakdown (durations in whole minutes, fmt_minutes) and
    each stage's share of the run's wall time (the first start .. last end
    across all records, one decimal); parallel-check items additionally get
    a detail block with each check's duration/percent and the fan-out wall
    time/percent against the same base. The base is the run's real wall
    time, NOT the sum of the row durations: parent loop steps and their
    nested iteration steps overlap (a do-while's duration includes its
    children), so summing the rows would inflate the denominator and shrink
    every percent. Missing data (no log.jsonl, no agent logs) degrades to
    an empty block — never a crash.
    """
    records = collect_latency(run_dir)
    if not records:
        return
    agent_ts = _agent_timestamps(state_dir)
    total_wall = max(r["end"] for r in records) - min(r["start"] for r in records)

    def pct(seconds: float) -> str:
        return f"{seconds / total_wall * 100:.1f}%" if total_wall > 0 else "0.0%"

    print()
    print("=== latency by stage ===")
    print(f"{'stage':<44}{'duration':>11}{'agent':>11}{'shell':>11}{'% wall':>8}")
    for rec in records:
        duration = max(0.0, rec["end"] - rec["start"])
        agent = _span_within(agent_ts, rec["start"], rec["end"])
        shell = max(0.0, duration - agent)
        print(
            "{:<44}{:>11}{:>11}{:>11}{:>8}".format(
                rec["id"][:44],
                fmt_minutes(duration),
                fmt_minutes(agent),
                fmt_minutes(shell),
                pct(duration),
            )
        )
    # Parallel checks: the fan-out item rows already carry each check's
    # duration; this block names the kinds and states the fan-out wall time.
    # The fan-out items are grouped BY RETRY-LOOP ITERATION: the wall time of
    # one fan-out batch must span only that iteration's items (min(start)..
    # max(end) over ALL iterations would stretch from the first check of
    # iteration 1 to the last check of the last iteration, swallowing the
    # merge/fix steps in between). The per-item rows carry the iteration too,
    # so identical kinds from different iterations do not visually merge.
    items = [(r, m) for r in records if (m := _FAN_OUT_ITEM_RE.match(r["id"]))]
    if items:
        print("parallel checks (fan-out):")
        iterations: dict[str, list[tuple[dict[str, Any], re.Match[str]]]] = {}
        for rec, m in items:
            # Group 1 is the engine's re-iteration namespacing suffix: the
            # engine writes every re-execution as <loop>:<step>:<iter+1> (its
            # _loop_iter is 0-based, but the written suffix is _loop_iter+1),
            # while the unprefixed first execution is iteration 1. So the
            # suffix of the N-th execution is N-1, and the 1-based display
            # key is the captured suffix + 1.
            iter_key = str(int(m.group(1)) + 1) if m.group(1) else "1"
            iterations.setdefault(iter_key, []).append((rec, m))
        for iter_key in sorted(iterations, key=int):
            batch = iterations[iter_key]
            print(f"  iteration {iter_key}:")
            for rec, m in batch:
                kind = _fan_out_kind(run_dir, rec["id"], int(m.group(2))) if run_dir else None
                label = kind if kind else f"check:{m.group(2)}"
                dur = max(0.0, rec["end"] - rec["start"])
                print(f"    {label:<40}{fmt_minutes(dur):>11}{pct(dur):>8}")
            wall_start = min(r["start"] for r, _ in batch)
            wall_end = max(r["end"] for r, _ in batch)
            wall = max(0.0, wall_end - wall_start)
            print("    {:<40}{:>11}{:>8}".format("fan-out wall", fmt_minutes(wall), pct(wall)))
    # The percent base is the run's wall time, so overlapping rows (a loop
    # step and its nested children, parallel checks) can sum to more than
    # 100%: the column is a share of the run, not a partition of it.
    print(
        "(percentages are shares of the run's wall time; nested and parallel "
        "steps overlap their parents, so the rows do not partition the run)"
    )
