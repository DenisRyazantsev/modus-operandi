"""LiveLines: per-process live status lines with cumulative token usage.

One responsibility: own the live status lines shown while the workflow runs
(ADR-0011, ADR-0012). Each active process — a role, or a role+fork for the
parallel review forks — has one line with the cumulative token/cost sums
accumulated from the agent-log events (opencode `step_finish` events; cursor
result events with a `usage` object, top-level token fields, or the same
`step_finish` fallback as opencode). While the current step has no agent
event yet, the block shows the synthesized harness line
`[hh:mm:ss] [harness] <spin> [<step> N/M]` without a token section; the
first agent event of the step (any type — the current cursor emits no
`step_start`) creates the process line and replaces the harness line. The
spinner frame shifts at most once per HEARTBEAT_SECONDS (1.0 s, ADR-0012),
so the block redrawn every 0.5 s monitor tick visibly "breathes" between
model turns without the text after the frame shifting.

The block is redrawn in place with ANSI on a TTY (the emitter owns the
drawing); on a non-TTY no ANSI is drawn — the harness line prints once per
step change (plain, no spinner, no heartbeat) and one plain line is returned
per event WITH usage (opencode `step_finish`, cursor usage events), which
the caller prints. When a workflow step completes, every active line is
fixed: returned as plain history lines and cleared, so the next event of the
same process opens a new line (the sums continue).
"""

from __future__ import annotations

import sys
import time
from typing import Any

from _run_pipeline_common import (
    HEARTBEAT_SECONDS,
    SPINNER_FRAMES,
    fmt_thousands,
    stamp,
)
from usage_parser import event_usage, is_result_style


class LiveLines:
    """Cumulative token/cost sums per process and the current live block."""

    def __init__(
        self,
        total_steps: int | None = None,
        tty: bool | None = None,
        backend: str = "opencode",
    ) -> None:
        self._totals: dict[tuple[str, str], dict[str, int | float]] = {}
        self._active: set[tuple[str, str]] = set()
        self._total_steps = total_steps
        self._tty = sys.stdout.isatty() if tty is None else tty
        # The price is shown only when the backend reports a cost: opencode
        # does, cursor does not (ADR-0012, same rule as the statistics).
        self._show_price = backend == "opencode"
        self._step_id = ""
        self._step_index: int | None = None
        self._step_has_events = False
        # The step label each active line was opened under and the harness
        # line was last rendered under: fix_all() renders the fixed copies
        # with these captured labels, so a completed step's lines keep their
        # own step even after the engine advanced current_step_id (bug fix).
        self._line_steps: dict[tuple[str, str], tuple[str, int | None]] = {}
        self._harness_step: tuple[str, int | None] | None = None
        # True once a result-style cursor event was seen: the step_finish
        # fallback is then disabled so a transitional build emitting both
        # shapes cannot double-count (bug fix).
        self._prefer_result = False
        # The spinner's last-shift timestamp: the frame shifts at most once
        # per HEARTBEAT_SECONDS (ADR-0012), so the line "breathes" between
        # model turns without the text after the frame moving.
        self._last_spin_ts = time.monotonic()
        self._spin_index = 0

    @property
    def step_index(self) -> int | None:
        return self._step_index

    @property
    def total_steps(self) -> int | None:
        return self._total_steps

    @property
    def tty(self) -> bool:
        return self._tty

    @property
    def step_has_events(self) -> bool:
        """True when the current step produced at least one agent event."""
        return self._step_has_events

    def set_step(self, step_id: str, step_index: int | None) -> bool:
        """Record the current workflow step (id and 0-based index).

        A negative index is clamped to 0; None (unreadable engine value)
        makes the line show the step without the N/M part, like a missing
        workflow file. Returns True when the step id changed to a non-empty
        value: the caller then prints the non-TTY step-start line (once per
        step) and the per-step event window is reset, so the harness line
        is shown until the step's first agent event (ADR-0012).
        """
        step_id = step_id or ""
        step_index = max(0, step_index) if step_index is not None else None
        changed = bool(step_id) and step_id != self._step_id
        self._step_id = step_id
        self._step_index = step_index
        if changed:
            self._step_has_events = False
        return changed

    def add_event(self, role: str, fork_id: str, event: dict[str, Any] | None) -> str | None:
        """Accumulate one agent-log event for the (role, fork_id) process.

        The process is active from the first ANY event — the current cursor
        emits no `step_start`, so any event type opens the process line
        (ADR-0012). Usage is read from cursor result events (a nested
        `usage` object with camelCase or snake_case keys, or top-level token
        fields of the event itself) and, as the opencode/old-cursor
        fallback, from `step_finish` events with `part.tokens`/`part.cost` —
        the fallback is disabled once a result-style event was seen, so a
        transitional build emitting both shapes cannot double-count (bug
        fix).
        A malformed event (a recognized-but-non-numeric token field, a
        non-dict `usage`/`tokens`/`cache`) is skipped whole: one broken
        event must not raise inside the monitor thread and silently kill the
        live status (bug fix). On a TTY the event only updates the block
        (None is returned); on a non-TTY the formatted line is returned once
        per event WITH usage, so the caller prints one plain line per agent
        turn.
        """
        if not isinstance(event, dict):
            return None
        try:
            usage = event_usage(event, self._prefer_result)
        except (AttributeError, TypeError, ValueError):
            return None
        if usage is not None and is_result_style(event):
            # The event parsed successfully through the modern shapes: the
            # step_finish fallback is disabled from here on, so a
            # transitional build emitting both shapes cannot double-count.
            # A malformed or unrecognized-shape result-style event is
            # skipped WITHOUT the flip — one broken event must not
            # permanently suppress all later token display (bug fix).
            self._prefer_result = True
        key = (role, fork_id)
        newly_active = key not in self._active
        self._active.add(key)
        self._step_has_events = True
        if newly_active:
            # The line is opened for the step that is current NOW: fix_all()
            # renders the fixed copy with this captured label, so the
            # completed step's lines keep their own step even after the
            # engine has advanced current_step_id (bug fix, ADR-0012).
            self._line_steps[key] = (self._step_id, self._step_index)
        if usage is None:
            # No recognized usage: the process line has no token section; a
            # non-TTY run prints nothing for such an event.
            return None
        acc = self._totals.setdefault(
            key,
            {
                "input": 0,
                "output": 0,
                "reasoning": 0,
                "cache_read": 0,
                "cache_write": 0,
                "cost": 0.0,
            },
        )
        for field, value in usage.items():
            acc[field] = acc.get(field, 0) + value
        if self._tty:
            return None
        return self._line(key)

    def _step_part(self, step_id: str, step_index: int | None) -> str:
        """The ` [<step> N/M]` part of a status line ("" without a step)."""
        if not step_id:
            return ""
        if self._total_steps is not None and step_index is not None:
            return f" [{step_id} {step_index + 1}/{self._total_steps}]"
        return f" [{step_id}]"

    def _spin(self) -> str:
        """The current spinner frame, one column wide.

        The frame shifts at most once per HEARTBEAT_SECONDS (1.0 s,
        ADR-0012): a redraw within the heartbeat keeps the current frame,
        the first redraw after it advances — the line "breathes" without
        the text after the frame shifting.
        """
        now = time.monotonic()
        if now - self._last_spin_ts >= HEARTBEAT_SECONDS:
            self._last_spin_ts = now
            self._spin_index = (self._spin_index + 1) % len(SPINNER_FRAMES)
        return SPINNER_FRAMES[self._spin_index]

    def _harness_line(self, step_id: str, step_index: int | None) -> str:
        """The TTY harness line: `[hh:mm:ss] [harness] <spin> [<step> N/M]`
        — no token section (ADR-0012)."""
        spin = f" {self._spin()}" if self._tty else ""
        return f"[{stamp()}] [harness]{spin}{self._step_part(step_id, step_index)}".rstrip()

    def harness_step_line(self) -> str:
        """The plain non-TTY step-start line (ADR-0012):
        `[hh:mm:ss] [harness] [<step> N/M]` — printed once per step change,
        when the step has no agent lines yet; no spinner and no heartbeat in
        a log."""
        return (
            f"[{stamp()}] [harness]{self._step_part(self._step_id, self._step_index)}"
        ).rstrip()

    def _tokens_part(self, acc: dict[str, int | float] | None) -> str:
        """The token/cost section of a process line; empty unless the
        process accumulated sums. `price` appears only when the backend
        reports a cost (opencode; cursor — no price, ADR-0012).

        A positive cost opens the whole section even when every token
        counter is zero: an opencode event that reports a cost should still
        surface its price; the `_show_price` guard keeps the rule
        opencode-only, because cursor never reports cost, so its zero-cost
        events must not open the section.
        """
        if acc is None:
            return ""
        # `cache_write` IS accumulated in the totals dict (it arrives in
        # every parsed usage dict — the shared event_usage output shape —
        # and the accumulator keeps the shape uniform) but is deliberately
        # NOT rendered: the live line shows cache read only (ADR-0011). The
        # has_totals tuple below therefore mirrors exactly the RENDERED
        # fields on purpose — an accumulated-only field must not open the
        # token section.
        has_totals = any(
            acc.get(field, 0) for field in ("cache_read", "reasoning", "input", "output")
        )
        if self._show_price and acc.get("cost", 0.0) > 0:
            has_totals = True
        if not has_totals:
            return ""
        part = (
            f"cache {fmt_thousands(acc['cache_read'])} · "
            f"reasoning {fmt_thousands(acc['reasoning'])} · "
            f"input {fmt_thousands(acc['input'])} · output {fmt_thousands(acc['output'])}"
        )
        if self._show_price:
            part += f" · price ${acc['cost']:.2f}"
        return " " + part

    def _line(self, key: tuple[str, str]) -> str:
        """One status line: `[hh:mm:ss] [<role>] <spin> [<step> N/M]
        cache ... · price $P` (no spinner on a non-TTY).

        The step label is the one captured when the line was opened, not the
        current step: the fixed copy of a completed step's line must keep
        the completed step's label even after the engine advanced
        current_step_id (bug fix).
        """
        role, fork_id = key
        label = role if not fork_id else f"{role}#{fork_id}"
        acc = self._totals.get(key)
        spin = f" {self._spin()}" if self._tty else ""
        step_id, step_index = self._line_steps.get(
            key, (self._step_id, self._step_index)
        )
        return (
            f"[{stamp()}] [{label}]{spin}"
            f"{self._step_part(step_id, step_index)}{self._tokens_part(acc)}"
        ).rstrip()

    def block(self) -> list[str]:
        """The current live block lines (TTY only).

        One line per active process; while the current step has no agent
        events, the synthesized harness line is shown instead, so the block
        never sits empty between steps and during long agent turns
        (ADR-0012). Each render refreshes the harness line's captured step
        label: the harness belongs to the step it was rendered under.
        """
        if not self._tty:
            return []
        if self._active:
            return [self._line(key) for key in sorted(self._active)]
        if self._step_id:
            self._harness_step = (self._step_id, self._step_index)
            return [self._harness_line(self._step_id, self._step_index)]
        return []

    def fix_all(self, completed_step_id: str | None = None) -> list[str]:
        """Fix every line on screen — the process lines and the harness line
        — as plain history lines and clear the block (TTY only; on a non-TTY
        each event already printed its own line).

        The fixed copies are rendered with the step label each line was
        opened/render under, never with the engine's already-advanced
        current_step_id: a completed step's lines keep their own step, and
        the harness line is fixed only when it belongs to the completed
        step (`completed_step_id`) — otherwise it stays live for the next
        step, so nothing is duplicated above the step marker (bug fix).
        The next event of the same process opens a new line with the
        continued sums; the per-step event window resets, so the next step
        starts with the harness line again (ADR-0012).
        """
        if not self._tty:
            # fix_all is also the step-boundary hook: the event window
            # resets so the next step's harness line can print, and _active
            # is cleared so the next event re-opens the process line and
            # re-captures the CURRENT step's label — a stale _active would
            # keep every later line labelled with the completed step
            # forever (bug fix). block() never draws on a non-TTY, so
            # clearing _active changes nothing else.
            self._active.clear()
            self._step_has_events = False
            return []
        lines = [self._line(key) for key in sorted(self._active)]
        if (
            not self._active
            and self._harness_step is not None
            and (completed_step_id is None or self._harness_step[0] == completed_step_id)
        ):
            # In production the monitor always passes the completed step's
            # id, so None means "no specific step known — fix whatever is
            # on screen" (a direct-call/test default), not a runtime path;
            # the id match is what prevents fixing a harness that belongs
            # to a different step.
            lines.append(self._harness_line(*self._harness_step))
        self._active.clear()
        self._step_has_events = False
        return lines
