"""Table column layout for the aligned log rows (ADR-0016).

One responsibility: own the column widths of the aligned log table — the
static role and step columns and the dynamic right-aligned token
sub-columns — and assemble rows from them. The role column is as wide as
the longest possible role label (the base roles plus the per-kind review
fork labels); the step column starts at the width of the widest step
bracket (computed from the workflow ids, with an allowance for the widest
N/M form) and widens when a runtime step id exceeds it; each token
sub-column is right-aligned and grows with the largest rendered value
seen so far in that column. Already-printed lines are never re-rendered.
"""

from __future__ import annotations

from check_review import KIND_ORDER
from display import stamp

BASE_ROLES = ("planner", "executor", "harness")

# The role column width: the widest role label, the base roles plus the
# per-kind review fork labels (the kinds are known before the run starts).
ROLE_WIDTH = max(
    len(f"[{label}]") for label in BASE_ROLES + tuple(f"planner#{kind}" for kind in KIND_ORDER)
)


def step_width_for(step_ids: list[str] | None, total_steps: int | None) -> int:
    """The static step column width: the widest `[<id> M/M]` bracket.

    An empty/unreadable id list or an unknown total degrades to 0 — the
    column then grows from the first rendered step (the runtime widening
    rule covers the degradation path too).
    """
    if not step_ids or not total_steps:
        return 0
    nm = f"{total_steps}/{total_steps}"
    return max(len(f"[{step_id} {nm}]") for step_id in step_ids)


class TableLayout:
    """The column widths and the row assembly (ADR-0016)."""

    def __init__(
        self,
        step_width: int = 0,
        role_width: int | None = None,
        tty: bool = True,
    ) -> None:
        self.role_width = ROLE_WIDTH if role_width is None else role_width
        self.step_width = max(0, step_width)
        self.tty = tty
        # Token sub-column name -> widest rendered value seen so far.
        self._token_widths: dict[str, int] = {}

    def role_field(self, role: str) -> str:
        return f"[{role}]".ljust(self.role_width)

    def step_field(self, step_id: str, step_index: int | None, total_steps: int | None) -> str:
        """The bracketed step part, padded to the current step column width.

        An empty step id renders as the full padding (an empty step
        column); a runtime step wider than the current column widens it
        for the rest of the run (ADR-0016).
        """
        if not step_id:
            return " " * self.step_width
        if total_steps is not None and step_index is not None:
            # step_index arrives 0-based from the engine and is displayed
            # 1-based for humans, the same rule ADR-0011 established for
            # the N/M progress.
            text = f"[{step_id} {step_index + 1}/{total_steps}]"
        else:
            text = f"[{step_id}]"
        if len(text) > self.step_width:
            self.step_width = len(text)
        return text.ljust(self.step_width)

    def empty_step(self) -> str:
        """The step column for rows that carry no step (captured output)."""
        return " " * self.step_width

    def tokens(self, pairs: list[tuple[str, str]]) -> str:
        """Render `name <value>` pairs right-aligned, tracking per-column widths."""
        parts = []
        for name, value in pairs:
            width = self._token_widths.get(name, 0)
            if len(value) > width:
                width = len(value)
                self._token_widths[name] = width
            parts.append(f"{name} {value.rjust(width)}")
        return " · ".join(parts)

    def row(self, role: str, spin: str, step: str, tail: str = "") -> str:
        """One aligned log row; `spin` (a one-column frame or a blank) is
        rendered only on a TTY."""
        line = f"[{stamp()}] {self.role_field(role)}"
        if self.tty:
            line += f" {spin}"
        line += f" {step}"
        if tail:
            line += f" {tail}"
        return line.rstrip()
