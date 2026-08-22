"""LiveLines: per-process live status lines with cumulative token usage.

One responsibility: own the live status lines shown while the workflow runs
(ADR-0011, ADR-0012, ADR-0016). Each active process — a role, or a role+fork
for the parallel review forks — has one aligned table row with the
cumulative token/cost sums accumulated from the agent-log events (opencode
`step_finish` events; cursor result events with a `usage` object, top-level
token fields, or the same `step_finish` fallback as opencode). While the
current step has no agent event yet, the block shows the synthesized
harness row `[hh:mm:ss] [harness] <spin> [<step> N/M]` without a token
section; the first agent event of the step (any type — the current cursor
emits no `step_start`) creates the process row and replaces the harness
row. The rows are assembled by TableLayout (ADR-0016): the role and step
columns are aligned, and the token sub-columns right-align and grow with
the widest value seen during the run. The spinner frame is chosen from the
elapsed time (rich-style time-based spinner): it advances every
HEARTBEAT_SECONDS (0.25 s, ADR-0013), so the block redrawn every 0.25 s
monitor tick visibly "breathes" between model turns, and a skipped tick
advances several frames at once instead of drifting the cadence.

The block is redrawn in place with ANSI on a TTY (the emitter owns the
drawing); on a non-TTY no ANSI is drawn — the harness row prints once per
step change (plain, no spinner, no heartbeat) and one plain row is returned
per event WITH usage (opencode `step_finish`, cursor usage events), which
the caller prints. When a workflow step completes, every active row is
pinned: returned as plain history rows and cleared, so the next event of
the same process opens a new row (the sums continue).
"""

from __future__ import annotations

import sys
import time
from typing import Any

from display import fmt_thousands
from table_format import TableLayout
from usage_parser import event_usage, is_result_style

# The live status line's spinner cadence (ADR-0012, ADR-0013): the frame is
# chosen from the elapsed time (rich-style time-based spinner), so it
# advances every heartbeat while the monitor redraws the block every 0.25 s
# tick — the line visibly "breathes" between model turns without the text
# after the frame shifting. A fixed constant: no config key.
HEARTBEAT_SECONDS = 0.25

# Single-column spinner frames (braille, each exactly one terminal column
# wide): the line is `[hh:mm:ss] [<role>] <frame> [<step> N/M] ...` — the
# frame never shifts the text that follows it (ADR-0012).
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class LiveLines:
    """Cumulative token/cost sums per process and the current live block."""

    def __init__(
        self,
        total_steps: int | None = None,
        tty: bool | None = None,
        backend: str = "opencode",
        step_width: int = 0,
        role_width: int | None = None,
    ) -> None:
        self._totals: dict[tuple[str, str], dict[str, int | float]] = {}
        self._active: set[tuple[str, str]] = set()
        self._total_steps = total_steps
        self._tty = sys.stdout.isatty() if tty is None else tty
        # The aligned log table columns (ADR-0016): the step column starts
        # at the static width computed from the workflow ids (0 when the
        # file is unreadable) and widens when a runtime step id exceeds it.
        self.layout = TableLayout(step_width=step_width, role_width=role_width, tty=self._tty)
        # The price is shown only when the backend reports a cost: opencode
        # does, cursor does not (ADR-0012, same rule as the statistics).
        self._show_price = backend == "opencode"
        self._step_id = ""
        self._step_index: int | None = None
        self._step_has_events = False
        # The step label each active line was opened under and the harness
        # line was last rendered under: pin_all() renders the pinned copies
        # with these captured labels, so a completed step's lines keep their
        # own step even after the engine advanced current_step_id (bug fix).
        self._line_steps: dict[tuple[str, str], tuple[str, int | None]] = {}
        self._harness_step: tuple[str, int | None] | None = None
        # True once a result-style cursor event was seen: the step_finish
        # fallback is then disabled so a transitional build emitting both
        # shapes cannot double-count (bug fix).
        self._prefer_result = False
        # The spinner's time origin: the frame is a function of the elapsed
        # time, so the 4 fps cadence (ADR-0013) never drifts even when a
        # monitor tick is skipped.
        self._t0 = time.monotonic()

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
            # The line is opened for the step that is current NOW: pin_all()
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

    def _spin(self) -> str:
        """The current spinner frame, one column wide.

        The frame is chosen from the elapsed time since LiveLines was
        created (the rich principle, ADR-0013): every HEARTBEAT_SECONDS
        (0.25 s) the frame advances, a skipped monitor tick advances several
        frames at once, and the block redrawn every 0.25 s tick visibly
        "breathes" without the text after the frame shifting.
        """
        frame = int((time.monotonic() - self._t0) / HEARTBEAT_SECONDS)
        return SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]

    def _harness_line(self, step_id: str, step_index: int | None) -> str:
        """The TTY harness row: role `harness`, the spinner, the step column
        and no token section (ADR-0012, ADR-0016)."""
        spin = self._spin() if self._tty else ""
        return self.layout.row(
            "harness",
            spin,
            self.layout.step_field(step_id, step_index, self._total_steps),
        )

    def harness_step_line(self) -> str:
        """The plain non-TTY step-start row (ADR-0012, ADR-0016): the same
        aligned columns, no spinner."""
        return self.layout.row(
            "harness",
            "",
            self.layout.step_field(self._step_id, self._step_index, self._total_steps),
        )

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
        pairs = [
            ("cache", fmt_thousands(acc["cache_read"])),
            ("reasoning", fmt_thousands(acc["reasoning"])),
            ("input", fmt_thousands(acc["input"])),
            ("output", fmt_thousands(acc["output"])),
        ]
        if self._show_price:
            pairs.append(("price", f"${acc['cost']:.2f}"))
        return self.layout.tokens(pairs)

    def _line(self, key: tuple[str, str]) -> str:
        """One aligned table row (ADR-0016): `[hh:mm:ss] [<role>] <spin>
        [<step> N/M] cache ... · price $P` (no spinner on a non-TTY).

        The step label is the one captured when the line was opened, not the
        current step: the fixed copy of a completed step's line must keep
        the completed step's label even after the engine advanced
        current_step_id (bug fix).
        """
        role, fork_id = key
        label = role if not fork_id else f"{role}#{fork_id}"
        acc = self._totals.get(key)
        spin = self._spin() if self._tty else ""
        step_id, step_index = self._line_steps.get(key, (self._step_id, self._step_index))
        return self.layout.row(
            label,
            spin,
            self.layout.step_field(step_id, step_index, self._total_steps),
            self._tokens_part(acc),
        )

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

    def pin_all(self, completed_step_id: str | None = None) -> list[str]:
        """Pin every line on screen — the process lines and the harness line
        — as plain history lines and clear the block (TTY only; on a non-TTY
        each event already printed its own line).

        The pinned copies are rendered with the step label each line was
        opened/render under, never with the engine's already-advanced
        current_step_id: a completed step's lines keep their own step, and
        the harness line is pinned only when it belongs to the completed
        step (`completed_step_id`) — otherwise it stays live for the next
        step, so nothing is duplicated above the step's captured output
        rows: the pinned rows are the only history above them, and the
        harness must not pin twice for the same completed step (bug fix).
        The next event of the same process opens a new line with the
        continued sums; the per-step event window resets, so the next step
        starts with the harness line again (ADR-0012).
        """
        if not self._tty:
            # pin_all is also the step-boundary hook: the event window
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
            # id, so None means "no specific step known — pin whatever is
            # on screen" (a direct-call/test default), not a runtime path;
            # the id match is what prevents pinning a harness that belongs
            # to a different step.
            lines.append(self._harness_line(*self._harness_step))
        self._active.clear()
        self._step_has_events = False
        return lines
