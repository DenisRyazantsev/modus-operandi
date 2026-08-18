"""Aggregate the run's token usage and print the run statistics block.

One responsibility: read the per-role session ids and the backend's usage
data (opencode: exported from the saved sessions via `opencode export`;
cursor: summed from the per-role .jsonl agent logs, whose result events
carry a `usage` field) and print the `=== run statistics ===` block. The
per-stage latency table (ADR-0009) lives in its own module
(latency_table.py) and is printed from here; this module does not parse the
engine's log.jsonl/state.json or know the fan-out step-id grammar. Missing
data always degrades to zero/dash values — the wrapper never fails here.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from _run_pipeline_common import fmt_duration, fmt_thousands
from latency_table import print_latency_table


def read_session_ids(state_dir: Path) -> dict[str, str]:
    """Map role -> session id from <state_dir>/sessions-<task-id>.json.

    The task id is taken from the <state_dir>/tasks/current symlink that the
    workflow's generate-task-id step maintains; a missing or broken symlink
    yields no ids (Path.resolve() never raises and always yields a final
    name here, so the sessions-file read below simply fails). Only roles
    with a non-empty id are returned.
    """
    try:
        task_id = current_task_id(state_dir)
        data = json.loads(
            (state_dir / f"sessions-{task_id}.json").read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        role: data[role]
        for role in ("planner", "executor")
        if isinstance(data.get(role), str) and data[role]
    }


def current_task_id(state_dir: Path) -> str:
    """The task id from the <state_dir>/tasks/current symlink ("" on failure)."""
    try:
        return (state_dir / "tasks" / "current").resolve().name
    except Exception:
        return ""


def export_session_info(session_id: str) -> dict[str, Any] | None:
    """Return the `info` dict of `opencode export <sessionID>`, or None.

    opencode prints the session export as JSON on stdout ("Exporting
    session: …" goes to stderr). The output is captured into a temporary
    file instead of a pipe: opencode (<= 1.18.x) can exit before its piped
    stdout is fully flushed once the session is larger than the pipe buffer,
    silently truncating the JSON. With a file the full output is available;
    a truncated run usually fails to parse, so the export is retried once.
    Any remaining failure — opencode missing, a non-zero exit, unparseable
    output — returns None and the caller degrades to zero/dash values
    instead of failing the run.
    """
    for _ in range(2):
        try:
            with tempfile.TemporaryFile(mode="w+b") as out:
                result = subprocess.run(
                    ["opencode", "export", session_id],
                    stdout=out,
                    stderr=subprocess.DEVNULL,
                    timeout=120,
                )
                if result.returncode != 0:
                    return None
                out.seek(0)
                try:
                    info = json.loads(out.read().decode("utf-8"))["info"]
                except Exception:
                    continue  # truncated/invalid export: retry once
                return info if isinstance(info, dict) else None
        except Exception:
            return None
    return None


def collect_usage(state_dir: Path, backend: str = "opencode") -> dict[str, int | float]:
    """Aggregate token usage and cost across the planner and executor roles.

    opencode: sums info.tokens.{input,output,reasoning},
    info.tokens.cache.{read,write} and info.cost of both roles into one dict;
    a role with no session id or a failed export contributes nothing. No live
    token accumulator is involved: opencode reports the full usage of each
    saved session itself.

    cursor: cursor-agent reports per-turn usage inside its JSON result events
    (the .jsonl agent logs), and `opencode export` knows nothing about cursor
    chat ids. The usage is therefore summed over every log line of the
    current task (role logs and the per-check fork logs alike); cursor
    reports no cost, which the statistics block prints as "n/a".
    """
    if backend == "cursor":
        return collect_cursor_usage(state_dir)
    totals: dict[str, int | float] = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost": 0.0,
    }
    for session_id in read_session_ids(state_dir).values():
        info = export_session_info(session_id)
        if info is None:
            continue
        tokens = info.get("tokens")
        if isinstance(tokens, dict):
            totals["input"] += int(tokens.get("input") or 0)
            totals["output"] += int(tokens.get("output") or 0)
            totals["reasoning"] += int(tokens.get("reasoning") or 0)
            cache = tokens.get("cache")
            if isinstance(cache, dict):
                totals["cache_read"] += int(cache.get("read") or 0)
                totals["cache_write"] += int(cache.get("write") or 0)
        cost = info.get("cost")
        if isinstance(cost, (int, float)):
            totals["cost"] += float(cost)
    return totals


def _empty_totals() -> dict[str, int | float]:
    return {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost": 0.0,
    }


def collect_cursor_usage(state_dir: Path) -> dict[str, int | float]:
    """Sum the usage fields of the current task's cursor .jsonl agent logs.

    Only files named after the current task (sessions-<task-id>-*.jsonl) are
    read, so previous tasks never bleed into the block. Each `-p` call emits
    one result event with that call's usage; summing every event yields the
    run's totals. The cursor CLI is in beta: the cache counters appeared both
    as a nested `cache` object and as top-level cacheReadTokens/cacheWriteTokens
    fields, so both shapes are read.
    """
    totals = _empty_totals()
    task_id = current_task_id(state_dir)
    logs_dir = state_dir / "logs"
    if not task_id or not logs_dir.is_dir():
        return totals
    for path in sorted(logs_dir.glob(f"sessions-{task_id}-*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except Exception:
                continue
            usage = event.get("usage")
            if not isinstance(usage, dict):
                continue
            totals["input"] += int(usage.get("inputTokens") or 0)
            totals["output"] += int(usage.get("outputTokens") or 0)
            totals["reasoning"] += int(usage.get("reasoningTokens") or 0)
            cache = usage.get("cache")
            if isinstance(cache, dict):
                totals["cache_read"] += int(cache.get("read") or 0)
                totals["cache_write"] += int(cache.get("write") or 0)
            else:
                totals["cache_read"] += int(usage.get("cacheReadTokens") or 0)
                totals["cache_write"] += int(usage.get("cacheWriteTokens") or 0)
    return totals


def print_run_statistics(
    state_dir: Path,
    elapsed: float,
    run_dir: Path | None = None,
    backend: str = "opencode",
) -> None:
    """Print the final `=== run statistics ===` block.

    Printed after the run on every completion path (success, failure, abort).
    Token counts use space thousand separators; wall time is HH:MM:SS.
    Missing session data degrades to zeros — the wrapper never fails here.
    cursor runs report no cost (the cursor API does not expose one in the
    JSON output), so the cost line prints "n/a" for them.
    When the run's log.jsonl is available, the per-stage latency table
    follows (printed by latency_table.print_latency_table, ADR-0009); missing
    data degrades to an empty table.
    """
    usage = collect_usage(state_dir, backend)
    print()
    print("=== run statistics ===")
    print(f"wall time: {fmt_duration(elapsed)}")
    print(
        "tokens: input {} · output {} · reasoning {}".format(
            fmt_thousands(usage["input"]),
            fmt_thousands(usage["output"]),
            fmt_thousands(usage["reasoning"]),
        )
    )
    print(
        "cache: read {} · write {}".format(
            fmt_thousands(usage["cache_read"]),
            fmt_thousands(usage["cache_write"]),
        )
    )
    if backend == "cursor":
        print("cost: n/a")
    else:
        print("cost: ${:.2f}".format(usage["cost"]))
    print_latency_table(state_dir, run_dir)
