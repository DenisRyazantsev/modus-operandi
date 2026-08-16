"""Query opencode for the session usage and print the run statistics block.

One responsibility: read the per-role session ids, export their token/cost
usage from opencode and print the `=== run statistics ===` block. Missing
data always degrades to zero/dash values — the wrapper never fails here.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from _run_pipeline_common import fmt_duration, fmt_thousands


def read_session_ids(state_dir: Path) -> dict[str, str]:
    """Map role -> session id from <state_dir>/sessions-<task-id>.json.

    The task id is taken from the <state_dir>/tasks/current symlink that the
    workflow's generate-task-id step maintains; a missing or broken symlink
    yields no ids (Path.resolve() never raises and always yields a final
    name here, so the sessions-file read below simply fails). Only roles
    with a non-empty id are returned.
    """
    try:
        task_id = (state_dir / "tasks" / "current").resolve().name
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


def export_session_info(session_id: str) -> dict | None:
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


def collect_usage(state_dir: Path) -> dict[str, int | float]:
    """Aggregate token usage and cost across the planner and executor sessions.

    Sums info.tokens.{input,output,reasoning}, info.tokens.cache.{read,write}
    and info.cost of both roles into one dict; a role with no session id or a
    failed export contributes nothing. No live token accumulator is involved:
    opencode reports the full usage of each saved session itself.
    """
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


def print_run_statistics(state_dir: Path, elapsed: float) -> None:
    """Print the final `=== run statistics ===` block.

    Printed after the run on every completion path (success, failure, abort).
    Token counts use space thousand separators; wall time is HH:MM:SS.
    Missing session data degrades to zeros — the wrapper never fails here.
    """
    usage = collect_usage(state_dir)
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
    print("cost: ${:.2f}".format(usage["cost"]))
