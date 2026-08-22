"""GateState: shared, thread-safe marker of an open human-gate menu."""

from __future__ import annotations

import threading
from typing import Any


class GateState:
    """Shared, thread-safe marker of an open human-gate menu, owning the
    gate lifecycle.

    The main thread (which reads specify's stdout) calls open(state) when it
    sees the first line of a gate menu window, capturing the gate's step id
    synchronously from the state it reads at that moment; update_and_closed()
    advances the lifecycle from each later state.json read — closing the gate
    (returning True) once the engine moves past the gate step. The monitor
    thread closes the gate explicitly when the wrapper is stopping (an
    aborted/rejected run may leave current_step_id on the gate forever).
    The lock keeps the flag and the id consistent across the two threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open = False
        self._gate_step_id: str | None = None

    def open(self, state: dict[str, Any] | None) -> None:
        """Mark a gate menu as open, capturing the gate's step id.

        The main thread passes the state.json read made the moment the menu
        opener line arrived: the menu is drawn only while the gate step is
        executing (its current_step_id was saved before input()), so the id
        read here is the gate's own. Capturing it now instead of on a later
        monitor tick removes the window in which a fast answer could make
        the first tick record the next step's id and leave the gate open
        through that whole step. An unreadable state (None) leaves the id
        for update_and_closed() to capture on the first readable tick.
        """
        with self._lock:
            self._open = True
            self._gate_step_id = (state or {}).get("current_step_id") or None

    def close(self) -> None:
        """Force the gate closed (e.g. the wrapper is stopping)."""
        with self._lock:
            self._open = False
            self._gate_step_id = None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def update_and_closed(self, state: dict[str, Any] | None) -> bool:
        """Advance the lifecycle from one state.json read; True when the gate closed.

        While the menu is open: when the captured id is missing (the open
        moment read failed), record current_step_id on the first readable
        tick; when the id differs from the captured one (the user answered
        and the engine moved on), close the gate and return True — the
        caller then flushes whatever output was buffered while the menu was
        open. A failed read (None) only skips the tick: it says nothing
        about the gate, and closing on it would print straight over the
        still-open menu — only a readable state with an empty or different
        current_step_id may close the gate. update_and_closed() performs no
        I/O and emits no output — it only mutates the gate's own state
        (under its lock). The "never emits output" clause is the contract
        the caller relies on, since the caller decides the flush. Loop
        iterations carry distinct suffixed ids (adr-loop:adr-gate:1,
        :2, …), so each re-drawn menu is tracked anew.
        """
        with self._lock:
            if not self._open:
                return False
            if state is None:
                # Transient read failure: skip the tick, keep the gate open.
                return False
            current = state.get("current_step_id") or ""
            if not self._gate_step_id:
                if current:
                    self._gate_step_id = current
                return False
            if current != self._gate_step_id:
                # Inlined instead of close(): the lock is not reentrant.
                self._open = False
                self._gate_step_id = None
                return True
            return False
