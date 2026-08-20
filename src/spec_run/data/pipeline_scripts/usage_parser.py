"""usage_parser: map one agent-log event to the internal usage dict.

One responsibility: own the backend usage-schema knowledge — opencode
`step_finish.part.tokens`, cursor `result` events with camelCase/snake_case/
nested-cache/top-level usage shapes, and the ValueError validation policy —
so a cursor CLI shape change touches exactly one file. The live status
lines (live_lines.py) and the run statistics
(run_statistics.collect_cursor_usage) both consume the same mapping: the
cursor schema lives in exactly one place (ADR-0012, SRP split).
"""

from __future__ import annotations

from typing import Any

# Cursor usage field names, camelCase and snake_case alike (ADR-0012): the
# mapping is shared by the nested `usage` object of result events, the
# top-level token fields of the event itself, and the snake_case variants
# (e.g. `cached_input_tokens` / `cache_read_input_tokens` for the cache
# read counter). The nested `cache` dict (`cache.read`/`cache.write`) is
# the either/or alternative to the flat cache names — and when BOTH are
# present in one event, the nested values OVERRIDE the flat ones per field
# (precedence, not accumulation; see _parse_usage).
TOKEN_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "input": ("inputTokens", "input_tokens"),
    "output": ("outputTokens", "output_tokens"),
    "reasoning": ("reasoningTokens", "reasoning_tokens"),
    "cache_read": (
        "cacheReadTokens",
        "cache_read_tokens",
        "cached_input_tokens",
        "cache_read_input_tokens",
    ),
    "cache_write": (
        "cacheWriteTokens",
        "cache_write_tokens",
        "cache_write_input_tokens",
    ),
}


def event_usage(
    event: dict[str, Any], prefer_result: bool = False
) -> dict[str, int | float] | None:
    """Parse the token/cost fields of one agent-log event.

    Returns the internal field dict (keys `input`, `output`, `reasoning`,
    `cache_read`, `cache_write`, `cost`), or None when the event carries no
    recognized usage. A recognized-but-malformed field raises ValueError
    etc. — the caller skips such an event whole (existing pattern).

    The shapes are precedence-ordered, not cumulative: a cursor CLI version
    emits one shape per event, and a nested `usage` object, when present,
    is taken as the whole usage — the flat and step_finish branches fire
    only when there is no `usage` key at all, because mixing the shapes of
    one event would double-count the same tokens. `prefer_result` (True
    once the task's logs have shown a result-style event) additionally
    disables the `step_finish` fallback: old cursor versions never emit
    result-style usage and new ones never emit `step_finish`, so a
    transitional build emitting both must not double-count (bug fix).
    """
    usage = event.get("usage")
    if isinstance(usage, dict):
        return _parse_usage(usage)
    if usage is not None:
        raise ValueError("non-dict usage")
    flat: dict[str, Any] = {}
    for names in TOKEN_FIELD_KEYS.values():
        for name in names:
            if name in event:
                flat[name] = event[name]
    if flat:
        return _parse_usage(flat)
    if not prefer_result and event.get("type") == "step_finish":
        part = event.get("part") or {}
        if not isinstance(part, dict):
            raise ValueError("non-dict part")
        tokens = part.get("tokens") or {}
        if not isinstance(tokens, dict):
            raise ValueError("non-dict tokens")
        cache = tokens.get("cache") or {}
        if not isinstance(cache, dict):
            raise ValueError("non-dict cache")
        return {
            "input": int(tokens.get("input") or 0),
            "output": int(tokens.get("output") or 0),
            "reasoning": int(tokens.get("reasoning") or 0),
            "cache_read": int(cache.get("read") or 0),
            "cost": float(part.get("cost") or 0),
        }
    return None


def is_result_style(event: dict[str, Any]) -> bool:
    """True when the event carries usage in a result-style shape — a
    `usage` object (valid or malformed) or top-level token fields — rather
    than the opencode/old-cursor `step_finish` fallback. The callers flip
    `prefer_result` once a task's logs have shown the modern shape, so a
    transitional build emitting both shapes cannot double-count (bug fix).
    """
    if event.get("usage") is not None:
        return True
    return any(
        name in event for names in TOKEN_FIELD_KEYS.values() for name in names
    )


def _parse_usage(data: dict[str, Any]) -> dict[str, int | float] | None:
    """Map a usage dict (camelCase or snake_case keys, nested cache) to the
    internal field names.

    None when none of the recognized names are present; ValueError when a
    present recognized field is not numeric (the caller then skips the whole
    event, existing pattern).
    """
    out: dict[str, int | float] = {}
    for field, names in TOKEN_FIELD_KEYS.items():
        for name in names:
            if name in data:
                value = data[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"non-numeric token field {name!r}")
                out[field] = int(value)
                break
    cache = data.get("cache")
    if isinstance(cache, dict):
        # The nested cache dict is the either/or alternative to the flat
        # cache names above (ADR-0012) — but when BOTH are present in one
        # event, the nested values deliberately OVERRIDE the flat ones per
        # field (cache_read/cache_write): a precedence, not a sum. Summing
        # the two would double-count the same tokens; the old run_statistics
        # code applied the same override rule — keep it (anti-double-count
        # contract).
        for field, name in (("cache_read", "read"), ("cache_write", "write")):
            if name in cache:
                value = cache[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"non-numeric cache field {name!r}")
                out[field] = int(value)
    elif cache is not None:
        raise ValueError("non-dict cache")
    return out or None
