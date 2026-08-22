"""LiveMonitor: coordinates step-result polling and agent-log tailing while specify runs."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from agent_log_tailer import AgentLogTailer
from buffered_emitter import BufferedEmitter
from gate_state import GateState
from live_lines import LiveLines
from run_id_discoverer import RunIdDiscoverer
from step_result_poller import StepResultPoller
from workflow_info import step_marker_index


class LiveMonitor:
    """Coordinates step-result polling and agent-log tailing while specify runs.

    Owns only the poll loop that wires its components together: the poller
    (state.json reads + finished-step events), the tailer (agent-log lines),
    the live status lines (ADR-0011: cumulative token sums per role/fork),
    the run-id discoverer and the buffered emitter (the gate-open output
    policy). Each component owns its own concern.
    """

    def __init__(
        self,
        run_state_dir: Path,
        prior_runs: set[str],
        logs_dir: Path | None = None,
        step_ids: list[str] | None = None,
        backend: str = "opencode",
    ) -> None:
        self.run_id: str = ""
        self._poller = StepResultPoller(run_state_dir, self.run_id)
        if logs_dir is None:
            logs_dir = Path.cwd() / ".workflow" / "logs"
        self._tailer = AgentLogTailer(logs_dir)
        self._stop = threading.Event()
        self._discoverer = RunIdDiscoverer(run_state_dir, prior_runs)
        self.gate = GateState()
        self._step_ids = step_ids
        total_steps = len(step_ids) if step_ids is not None else None
        # The backend (opencode/cursor) reaches the live lines through the
        # monitor: the price is omitted on cursor, which reports no cost
        # (ADR-0012).
        self._live = LiveLines(total_steps=total_steps, backend=backend)
        self._emitter = BufferedEmitter(self.gate)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self) -> None:
        self._thread.join()

    def emit_stdout(self, line: str) -> None:
        """Echo one of specify's own stdout lines (called by main())."""
        self._emitter.emit_stdout(line)

    def clear_live(self) -> None:
        """Clear the drawn live block (called by main() before final output)."""
        self._emitter.clear_live()

    def read_current_state(self) -> dict[str, Any] | None:
        """Read the current run's state.json, discovering the run id first.

        Used by main() for the synchronous gate-id capture at the moment a
        menu opener line arrives; the monitor's own poll may not have
        discovered the run id yet. Runs on the calling (main) thread, with
        no lock — that is deliberate: both this method and the monitor's
        poll write the same deterministic value (the single new run
        directory), and attribute assignment is atomic under the GIL, so a
        torn state cannot be observed. The discovery is delegated to the
        discoverer; the raw state.json read to the poller (which owns it).
        """
        run_id = self.run_id or self._discoverer.discover()
        if not run_id:
            return None
        self.run_id = run_id
        self._poller.run_id = run_id
        return self._poller.read_state()

    def _drain_tailer(self) -> None:
        """Feed the appended agent-log events into the live status lines."""
        for role, fork_id, _text, event in self._tailer.tail():
            line = self._live.add_event(role, fork_id, event)
            if line is not None:
                # Non-TTY: one plain line per step_finish event.
                self._emitter.emit_live([line], plain=True)

    def _poll_once(self, run_id: str | None = None) -> None:
        if run_id is None:
            # The known run id (from the stdout "Run ID:" line) is
            # authoritative; only when it is still unknown is a new run
            # directory discovered.
            run_id = self.run_id or self._discoverer.discover()
        state: dict[str, Any] | None = None
        step_changed = False
        if run_id:
            self.run_id = run_id
            self._poller.run_id = run_id
            # state.json is read once per tick: the gate check needs
            # current_step_id, the poller reuses the same data, and the live
            # lines need the current step for the N/M progress.
            state = self._poller.read_state()
            if self.gate.update(state):
                # The engine moved past the gate: flush what was buffered
                # while the menu was open, then resume live emission.
                self._emitter.flush()
            raw_index = (state or {}).get("current_step_index")
            try:
                step_index = int(raw_index) if raw_index is not None else 0
            except (TypeError, ValueError):
                # An unreadable index (e.g. a non-numeric value): the live
                # line shows the step without N/M rather than crash the
                # monitor thread.
                step_index = None
            step_changed = self._live.set_step(
                (state or {}).get("current_step_id") or "", step_index
            )
        # Agent logs are drained BEFORE the step results: a step's final
        # agent events must accumulate before its "--- step X (completed)"
        # marker, not after it.
        self._drain_tailer()
        if run_id:
            for step_id, result in self._poller.poll(state):
                # One more tailer drain per finished step: events written
                # after the drain above (e.g. the agent's final reply before
                # the step completed) accumulate before this step's marker.
                self._drain_tailer()
                # Pin the live lines before the marker: they stay in the
                # terminal as history (printed plainly), then the marker
                # prints. The completed step's id is passed so the pinned
                # copies keep the completed step's label — the engine has
                # usually already advanced current_step_id to the next step
                # by now (bug fix). The next event of the same process opens
                # a new line with the continued sums.
                pinned = self._live.pin_all(step_id)
                if pinned:
                    self._emitter.emit_live(pinned, plain=True)
                # The marker shows the completed step's OWN position in the
                # workflow (the engine's current_step_index has usually
                # already advanced to the next step by the time the result
                # is polled); an unknown step degrades to no N/M.
                marker_index = step_marker_index(step_id, self._step_ids)
                self._emitter.emit_step(step_id, result, marker_index, self._live.total_steps)
            # Redraw the live block after any fixed lines / markers (TTY
            # only; on a non-TTY the block is empty).
            self._emitter.emit_live(self._live.block())
            if step_changed and not self._live.tty and not self._live.step_has_events:
                # The step-start line is emitted after the drain on purpose:
                # set_step resets the per-step event window, the drain then
                # marks the window as having events, and only a step with no
                # agent lines yet gets the harness announcement — moving the
                # drain above the state read would silently duplicate
                # announcements (ADR-0012).
                self._emitter.emit_live([self._live.harness_step_line()], plain=True)

    def finish(self) -> None:
        """One final poll after specify exits: late step results may still land.

        The monitor thread has already stopped by now, so also drain the
        agent logs once here — otherwise lines written between the last 0.25s
        poll tick and process exit (e.g. the agent's final reply before a
        step completes) are never shown and stay only in the .jsonl files.
        The drawn live block is cleared afterwards so the final run
        statistics print on a clean screen.
        """
        self._poll_once()
        self._emitter.clear_live()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._poll_once()
                # A 0.25 s tick (ADR-0013): the spinner advances every
                # 0.25 s, so the block must be redrawn at least that often —
                # a slower tick would physically cap the animation at 2 fps.
                time.sleep(0.25)
        finally:
            # The wrapper is stopping. An aborted/rejected run may leave
            # current_step_id on the gate, so the gate would never close on
            # its own: close it here and flush whatever was buffered while
            # it was open — nothing is lost.
            self.gate.close()
            self._emitter.flush()
