"""Read and react to the engine's stdout while specify runs.

One responsibility: own the wrapper's engine-stdout consumption policy —
the read loop, the per-line echo/filter decisions (ADR-0013: drop the
engine's step-start/header lines, re-emit errors as `[harness]` rows,
fail-open echo), the run-id capture and the gate-menu dispatch. The line
classification lives in engine_output.py and the gate recognition in
feedback_gate.py; only the action policy lives here. run_pipeline.py only
calls consume_output.
"""

from __future__ import annotations

import subprocess
import threading

from display import stamp
from engine_output import (
    is_engine_error,
    is_engine_header,
    is_engine_step_start,
    is_gate_menu_opener,
    run_id_from_text,
)
from feedback_editor import open_feedback_editor
from feedback_gate import is_feedback_gate
from live_monitor import LiveMonitor
from notify import play_signal


def handle_gate_menu(
    monitor: LiveMonitor,
    state_dir: str,
    master_fd: int | None,
    forward_pause: threading.Event,
) -> None:
    """Own the wrapper's response to a human-gate menu window on screen.

    The gate's step id is captured synchronously from the state read right
    now — not on a later monitor tick, when a fast answer could already have
    moved current_step_id. The feedback gate (motivation-feedback-gate) is
    answered by the wrapper through the terminal editor (and never signals);
    every other gate plays the victory.wav signal for the human.
    """
    state = monitor.read_current_state()
    monitor.gate.open(state)
    step_id = (state or {}).get("current_step_id")
    if is_feedback_gate(step_id):
        # The feedback gate: the wrapper owns the answer. feedback.md is
        # created in the current task dir (never overwritten; a NEW file is
        # seeded with the numbered open questions of the gate's document —
        # study.md for a motivation gate — and opened
        # in the terminal editor; on editor close the gate is answered with
        # `continue` so the workflow continues (the revise step reads
        # feedback.md). If no editor can run, the gate stays interactive for
        # manual input. No victory sound is played for this gate in any path.
        if master_fd is not None:
            open_feedback_editor(
                state_dir,
                forward_pause,
                master_fd,
                step_id,
            )
    else:
        # The human is needed: play the same signal used for a finished run
        # (success or failure alike).
        play_signal()


def consume_output(
    proc: subprocess.Popen[str],
    monitor: LiveMonitor,
    state_dir: str,
    master_fd: int | None,
    forward_pause: threading.Event,
) -> str:
    """Read specify's stdout until EOF, echoing it timestamped and handling gates.

    The echo is filtered to the wrapper's OWN format (ADR-0013): the
    engine's step-start lines (`▸ ...`) and one-time headers
    (`Running workflow:`/`Version:`/`Status:`/`Run ID:`) are not printed;
    engine errors and diagnostics (`Error:`/`Workflow failed:`/`Warning:`)
    are re-printed as aligned `[hh:mm:ss] [harness]` table rows (ADR-0016);
    the interactive gate menu and any unknown line echo unchanged
    (fail-open). The run id is parsed BEFORE the filtering, so the resume
    message still works. Returns the run id parsed from specify's final
    "Run ID:" line ("" if the line never appeared); the run id is also
    stored on the monitor so late state reads can locate the run directory.
    """
    run_id = ""
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        # The run id must be parsed before the engine-line filtering: the
        # "Run ID:" line is dropped from the echo (ADR-0013), but it feeds
        # the resume message on failure.
        if not run_id:
            run_id = run_id_from_text(line)
            if run_id:
                monitor.run_id = run_id
        if is_gate_menu_opener(line):
            handle_gate_menu(monitor, state_dir, master_fd, forward_pause)
        # The echo goes through the emitter: the live block is cleared
        # before the line (and redrawn after, unless a gate menu is open).
        if is_engine_step_start(line) or is_engine_header(line):
            # Strictly our format (ADR-0013): engine progress and one-time
            # headers are not echoed.
            continue
        if is_engine_error(line):
            # Engine errors/diagnostics are not dropped: re-emitted in the
            # wrapper's own [harness] table format (ADR-0013, ADR-0016).
            monitor.emit_stdout(monitor.harness_row(line))
        else:
            monitor.emit_stdout(f"[{stamp()}] {line}")
    return run_id
