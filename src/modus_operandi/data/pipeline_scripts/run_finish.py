"""Run teardown and outcome reporting for the run-pipeline.py wrapper.

One responsibility: own what happens after specify's stdout reaches EOF —
stopping the input forwarding and the monitor (with a late drain), reaping
the child, and presenting the outcome: the failure row + resume hint, the
statistics block and the victory signal. This presentation/lifecycle
concern changes independently of the orchestration flow; run_pipeline.py
only calls finalize_run.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from live_monitor import LiveMonitor
from notify import play_signal
from pty_spawn import stop_forwarding
from run_statistics import print_run_statistics


def _report_failure(rc: int, run_id: str, monitor: LiveMonitor) -> None:
    """Print the failure row and the resume hint (the run's failure UX)."""
    print()
    print(monitor.harness_row(f"run failed (exit {rc})"))
    if run_id:
        print(monitor.harness_row(f"resume with: specify workflow resume {run_id}"))


def _report_statistics(state_dir: str, t0: float, t1: float, run_id: str, backend: str) -> None:
    """Print the statistics block and play the victory signal on every path.

    The statistics block prints on every completion path and never fails:
    missing session data or a failed `opencode export` degrade to zeros
    (cursor runs aggregate their usage from the agent logs instead). The
    run directory feeds the per-stage latency table (ADR-0009); a missing
    run dir degrades to an empty table.
    """
    run_dir = None
    if run_id:
        run_dir = Path.cwd() / ".specify" / "workflows" / "runs" / run_id
    print_run_statistics(Path.cwd() / state_dir, t1 - t0, run_dir, backend)
    # The completion signal: one victory.wav for a finished run, success or
    # failure alike. (The gate-open signal is played in
    # stdout_reader.handle_gate_menu; the "one signal for every event"
    # policy — gate-open except the feedback gate, success, failure — is
    # stated in play_signal()'s docstring, where the whole signal surface
    # is visible.)
    play_signal()


def finalize_run(
    proc: subprocess.Popen[str],
    monitor: LiveMonitor,
    run_id: str,
    t0: float,
    state_dir: str,
    master_fd: int | None,
    forward_thread: threading.Thread | None,
    forward_stop: threading.Event,
    backend: str,
) -> int:
    """Stop forwarding and the monitor, reap specify, and report the outcome.

    Runs on every completion path (including when the read loop raised):
    reaping the child even then keeps proc.returncode set, so the failure
    message never prints "exit None". Returns the run's exit code after
    printing the failure message, the resume command, the statistics block
    and the victory signal — none of the reporting ever changes the exit
    code. The four steps are delegated: stop forwarding, reap and stop the
    monitor (with a late drain), report the failure if any, report the
    statistics and the sound.
    """
    stop_forwarding(master_fd, forward_stop, forward_thread)
    # Reap the child even when the read loop above raised (OSError,
    # KeyboardInterrupt) before reaching proc.wait(): otherwise
    # proc.returncode would be None and the failure message would print
    # "run failed (exit None)". wait() is a no-op when the process already
    # exited.
    proc.wait()
    t1 = time.monotonic()
    # Stop and join the monitor thread first: finish() below would
    # otherwise race _run()'s poll() on the shared _seen_steps state and
    # can duplicate a step's output.
    monitor.stop()
    monitor.join()
    # The stdout "Run ID:" line may never appear (e.g. the workflow failed
    # before the final status block), but the run directory was already
    # discovered; drain late results and logs either way.
    rid = run_id or monitor.run_id
    if rid:
        time.sleep(0.2)
        monitor.finish()
    rc = proc.returncode
    if rc is None:
        rc = 1
    if rc != 0:
        _report_failure(rc, rid, monitor)
    _report_statistics(state_dir, t0, t1, rid, backend)
    return rc
