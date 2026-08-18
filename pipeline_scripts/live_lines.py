"""LiveLines: per-process live status lines with cumulative token usage.

One responsibility: own the live status lines shown while the workflow runs
(ADR-0011). Each active process — a role, or a role+fork for the parallel
review forks — has one line with the cumulative token/cost sums accumulated
from the agent-log `step_finish` events. The block is redrawn in place with
ANSI on a TTY (the emitter owns the drawing); on a non-TTY the same line is
returned once per `step_finish` event, without ANSI, and the caller prints
it as a plain line. When a workflow step completes, every active line is
fixed: returned as plain history lines and cleared, so the next
`step_finish` of the same process opens a new line (the sums continue).
"""

from __future__ import annotations

import sys
from typing import Any

from _run_pipeline_common import fmt_thousands, stamp


class LiveLines:
    """Cumulative token/cost sums per process and the current live block."""

    def __init__(self, total_steps: int | None = None, tty: bool | None = None) -> None:
        self._totals: dict[tuple[str, str], dict[str, int | float]] = {}
        self._active: set[tuple[str, str]] = set()
        self._total_steps = total_steps
        self._tty = sys.stdout.isatty() if tty is None else tty
        self._step_id = ""
        self._step_index: int | None = None

    @property
    def step_index(self) -> int | None:
        return self._step_index

    @property
    def total_steps(self) -> int | None:
        return self._total_steps

    def set_step(self, step_id: str, step_index: int | None) -> None:
        """Record the current workflow step (id and 0-based index).

        A negative index is clamped to 0; None (unreadable engine value)
        makes the line show the step without the N/M part, like a missing
        workflow file.
        """
        self._step_id = step_id or ""
        self._step_index = max(0, step_index) if step_index is not None else None

    def add_event(self, role: str, fork_id: str, event: dict[str, Any] | None) -> str | None:
        """Accumulate one agent-log event for the (role, fork_id) process.

        Only `step_finish` events carry tokens; every other event type is
        ignored. On a TTY the event only updates the block (None is
        returned); on a non-TTY the formatted line is returned so the caller
        prints one plain line per `step_finish`. A malformed event (a
        non-numeric token/cost field, a non-dict `tokens`/`cache`) is
        skipped whole: one broken event must not raise inside the monitor
        thread and silently kill the live status (bug fix).
        """
        if not isinstance(event, dict) or event.get("type") != "step_finish":
            return None
        try:
            part = event.get("part") or {}
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            t_input = int(tokens.get("input") or 0)
            t_output = int(tokens.get("output") or 0)
            t_reasoning = int(tokens.get("reasoning") or 0)
            t_cache_read = int(cache.get("read") or 0)
            t_cost = float(part.get("cost") or 0)
        except (AttributeError, TypeError, ValueError):
            return None
        key = (role, fork_id)
        acc = self._totals.setdefault(
            key, {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cost": 0.0}
        )
        acc["input"] += t_input
        acc["output"] += t_output
        acc["reasoning"] += t_reasoning
        acc["cache_read"] += t_cache_read
        acc["cost"] += t_cost
        self._active.add(key)
        if self._tty:
            return None
        return self._line(key)

    def _line(self, key: tuple[str, str]) -> str:
        """One status line: `[hh:mm:ss] [<role>] [<step> N/M] cache ... · price $P`."""
        role, fork_id = key
        label = role if not fork_id else f"{role}#{fork_id}"
        acc = self._totals[key]
        step_part = ""
        if self._step_id:
            if self._total_steps is not None and self._step_index is not None:
                step_part = f" [{self._step_id} {self._step_index + 1}/{self._total_steps}]"
            else:
                step_part = f" [{self._step_id}]"
        return (
            f"[{stamp()}] [{label}]{step_part} "
            f"cache {fmt_thousands(acc['cache_read'])} · "
            f"reasoning {fmt_thousands(acc['reasoning'])} · "
            f"input {fmt_thousands(acc['input'])} · output {fmt_thousands(acc['output'])} · "
            f"price ${acc['cost']:.2f}"
        )

    def block(self) -> list[str]:
        """The current live block lines, one per active process (TTY only)."""
        if not self._tty:
            return []
        return [self._line(key) for key in sorted(self._active)]

    def fix_all(self) -> list[str]:
        """Fix every active line: return them as plain history lines and
        clear the block (TTY only — on a non-TTY each `step_finish` already
        printed its own line). The next `step_finish` of the same process
        opens a new line with the continued sums.
        """
        if not self._tty:
            return []
        lines = [self._line(key) for key in sorted(self._active)]
        self._active.clear()
        return lines
