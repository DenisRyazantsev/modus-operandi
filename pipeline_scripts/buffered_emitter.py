"""BufferedEmitter: the gate-open output buffering policy for live events."""

from __future__ import annotations

from _run_pipeline_common import print_log_event, print_step_result
from gate_state import GateState


class BufferedEmitter:
    """Owns the gate-open output buffering policy for live events.

    While a human-gate menu is on screen (GateState raised by the stdout
    reader), finished steps and agent-log lines are appended to the buffer
    instead of printed; flush() prints them — logs before step markers — and
    is called when the engine moves past the gate or the wrapper stops.
    """

    def __init__(self, gate: GateState) -> None:
        self._gate = gate
        self._buffered_steps: list[tuple[str, dict]] = []
        self._buffered_logs: list[tuple[str, str]] = []

    def emit_step(self, step_id: str, result: dict) -> None:
        """Buffer or print one finished step result, per the gate state."""
        if self._gate.is_open:
            self._buffered_steps.append((step_id, result))
        else:
            print_step_result(step_id, result)

    def emit_log(self, role: str, text: str) -> None:
        """Buffer or print one agent-log line, per the gate state."""
        if self._gate.is_open:
            self._buffered_logs.append((role, text))
        else:
            print_log_event(role, text)

    def flush(self) -> None:
        """Print the events that were buffered while the gate menu was open.

        Logs are flushed before the step markers so the "agent lines precede
        the step's completion marker" invariant holds for buffered output
        too; this runs right before live printing resumes, so nothing is
        lost.
        """
        for role, text in self._buffered_logs:
            print_log_event(role, text)
        self._buffered_logs.clear()
        for step_id, result in self._buffered_steps:
            print_step_result(step_id, result)
        self._buffered_steps.clear()

    @property
    def buffered_steps(self) -> list[tuple[str, dict]]:
        return self._buffered_steps

    @property
    def buffered_logs(self) -> list[tuple[str, str]]:
        return self._buffered_logs
