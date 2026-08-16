"""LiveMonitor: coordinates step-result polling and agent-log tailing while specify runs."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from agent_log_tailer import AgentLogTailer
from buffered_emitter import BufferedEmitter
from gate_state import GateState
from run_id_discoverer import RunIdDiscoverer
from step_result_poller import StepResultPoller


class LiveMonitor:
    """Coordinates step-result polling and agent-log tailing while specify runs.

    Owns only the poll loop that wires its components together: the poller
    (state.json reads + finished-step events), the tailer (agent-log lines),
    the run-id discoverer and the buffered emitter (the gate-open output
    policy). Each component owns its own concern.
    """

    def __init__(
        self,
        run_state_dir: Path,
        prior_runs: set[str],
        logs_dir: Path | None = None,
    ) -> None:
        self.run_id: str = ""
        self._poller = StepResultPoller(run_state_dir, self.run_id)
        if logs_dir is None:
            logs_dir = Path.cwd() / ".workflow" / "logs"
        self._tailer = AgentLogTailer(logs_dir)
        self._stop = threading.Event()
        self._discoverer = RunIdDiscoverer(run_state_dir, prior_runs)
        self.gate = GateState()
        self._emitter = BufferedEmitter(self.gate)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self) -> None:
        self._thread.join()

    def read_current_state(self) -> dict | None:
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

    def _poll_once(self, run_id: str | None = None) -> None:
        if run_id is None:
            # The known run id (from the stdout "Run ID:" line) is
            # authoritative; only when it is still unknown is a new run
            # directory discovered.
            run_id = self.run_id or self._discoverer.discover()
        state: dict | None = None
        if run_id:
            self.run_id = run_id
            self._poller.run_id = run_id
            # state.json is read once per tick: the gate check needs
            # current_step_id, the poller reuses the same data.
            state = self._poller.read_state()
            if self.gate.update(state):
                # The engine moved past the gate: flush what was buffered
                # while the menu was open, then resume live emission.
                self._emitter.flush()
        # Agent logs are drained BEFORE the step results: a step's final
        # agent lines must print before its "--- step X (completed)" marker,
        # not after it. The logs do not depend on the run id, so they are
        # drained on every tick regardless.
        for role, text in self._tailer.tail():
            self._emitter.emit_log(role, text)
        if run_id:
            for step_id, result in self._poller.poll(state):
                # One more tailer drain per finished step: lines written
                # after the drain above (e.g. the agent's final reply before
                # the step completed) print before this step's marker.
                for role, text in self._tailer.tail():
                    self._emitter.emit_log(role, text)
                self._emitter.emit_step(step_id, result)

    def finish(self) -> None:
        """One final poll after specify exits: late step results may still land.

        The monitor thread has already stopped by now, so also drain the
        agent logs once here — otherwise lines written between the last 0.5s
        poll tick and process exit (e.g. the agent's final reply before a
        step completes) are never shown and stay only in the .jsonl files.
        """
        self._poll_once()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._poll_once()
                time.sleep(0.5)
        finally:
            # The wrapper is stopping. An aborted/rejected run may leave
            # current_step_id on the gate, so the gate would never close on
            # its own: close it here and flush whatever was buffered while
            # it was open — nothing is lost.
            self.gate.close()
            self._emitter.flush()
