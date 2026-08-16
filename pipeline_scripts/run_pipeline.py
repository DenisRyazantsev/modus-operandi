#!/usr/bin/env python3
"""run-pipeline.py - run a specify workflow with timestamps and live logs.

specify hides a failing step's stdout/stderr and prints no timestamps. This
wrapper streams specify's own output with an hh:mm:ss prefix, polls the run
state (.specify/workflows/runs/<run_id>/) and prints each step's output as
it finishes, tails the per-role agent logs (<state_dir>/logs/) live, and on
failure prints the resume command.

While specify waits for interactive input on a human gate (its menu window
"┌─ Gate …" is drawn on screen), step results and agent-log lines are
buffered instead of printed, so the window is not flooded; the buffer is
flushed as soon as the engine moves past the gate or the wrapper exits.

On a terminal run the wrapper owns specify's stdin through a pty: specify's
gate step prompts only while its stdin is a TTY, so the slave end is given
to specify (keeping sys.stdin.isatty() True inside it) and terminal input is
forwarded into the master end, so interactive gates keep working while the
wrapper can answer the ADR revise feedback gate itself. When that gate opens
the wrapper creates <state_dir>/tasks/current/feedback.md (never overwriting
an existing file), opens it in the terminal editor ($VISUAL, then $EDITOR,
then nano, then vi), and on editor close answers the gate with `continue` so
the workflow resumes (adr-revise reads feedback.md). If no editor can run
(non-TTY or none found), the file is still created and the gate stays
interactive for manual input. On a non-TTY run no pty is used and specify
keeps the inherited stdin, so gates keep going PAUSED exactly as before.

When the run finishes (success, failure or abort alike) the wrapper prints a
`=== run statistics ===` block: the wall-clock run time and the token/cost
usage of the planner and executor sessions, queried from opencode by session
id. It also plays a single victory.wav signal on gate-open (except the ADR
revise feedback gate), on success and on failure; the sound and the
statistics never change the exit code.

Agent logs are displayed aligned (role labels padded to the longest role
name), agent reasoning longer than 100 chars is truncated for the console
(the full text stays in the .jsonl files), and only lines appended during
the current run are shown (pre-existing log files are baselined at startup).
A step's agent lines print before the step's "--- step X (completed)"
marker.

Usage: run-pipeline.py <workflow-id-or-path> [extra specify args...]
  run-pipeline.py review-pipeline
  run-pipeline.py adr-pipeline -i feature="..."
  run-pipeline.py ~/.config/spec-kit-llm-client/review-pipeline.yml -i branch-diff=true
  run-pipeline.py --backend cursor adr-pipeline -i feature="..."   # backend override

Environment:
  SKLC_CONFIG          path of the installed config.yml (default: derived
                       from this wrapper's location)
  SKLC_SCRIPTS_DIR     directory of the installed pipeline scripts (set to
                       this wrapper's own directory for the specify child)
  SKLC_ATTACH_FLAG     opencode attach flag passed to run-agent.sh/name-task.sh
                       (set from workflow.use_serve in the installed config)

The wrapper also computes the effective backend for the run (a leading
`--backend <opencode|cursor>` CLI flag wins over the `backend:` config key,
which defaults to opencode) and exports it to the workflow steps through
SKLC_BACKEND plus the role models of the active backend through
SKLC_PLANNER_MODEL / SKLC_EXECUTOR_MODEL (run-agent.sh/name-task.sh read
them; the opencode branch ignores the models - the agent files carry them).

This file is the entry point of a module split, one concern per file: the
live-monitor classes live in run_id_discoverer.py / step_result_poller.py /
agent_log_tailer.py / gate_state.py / buffered_emitter.py / live_monitor.py
and the shared constants and pure helpers in _run_pipeline_common.py; the
config-to-invocation mapping in config_invocation.py, the run statistics in
run_statistics.py, the victory.wav policy in notify.py, the feedback gate's
editor interaction in feedback_editor.py (with the editor chain in
editor.py) and the pty plumbing in pty_spawn.py. This module owns the main()
orchestration flow and re-exports every public name so the wrapper keeps its
single import surface.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from _run_pipeline_common import (
    existing_run_ids,
    fmt_duration,
    fmt_thousands,
    is_feedback_gate,
    is_gate_menu_opener,
    print_log_event,
    print_step_result,
    render_log_event,
    role_label,
    run_id_from_text,
    stamp,
    truncate,
)
from agent_log_tailer import AgentLogTailer
from buffered_emitter import BufferedEmitter
from config_invocation import (
    BACKENDS,
    CONFIG_PATH,
    build_specify_invocation,
    effective_backend,
    load_config,
    normalize_config,
    role_model,
)
from feedback_editor import create_feedback_file, open_feedback_editor, resolve_editor
from gate_state import GateState
from live_monitor import LiveMonitor
from notify import SOUND_FILE, notify
from pty_spawn import _spawn_specify, forward_terminal_input, set_pty_no_echo
from run_id_discoverer import RunIdDiscoverer
from run_statistics import (
    collect_usage,
    export_session_info,
    print_run_statistics,
    read_session_ids,
)
from step_result_poller import StepResultPoller

# Public surface of the wrapper: the classes and the helper functions, so
# tests and callers keep a single import target (the run_pipeline module).
__all__ = [
    "AgentLogTailer",
    "BufferedEmitter",
    "GateState",
    "LiveMonitor",
    "RunIdDiscoverer",
    "StepResultPoller",
    "BACKENDS",
    "CONFIG_PATH",
    "SOUND_FILE",
    "build_specify_invocation",
    "collect_usage",
    "create_feedback_file",
    "effective_backend",
    "existing_run_ids",
    "export_session_info",
    "fmt_duration",
    "fmt_thousands",
    "forward_terminal_input",
    "is_feedback_gate",
    "is_gate_menu_opener",
    "load_config",
    "normalize_config",
    "notify",
    "open_feedback_editor",
    "print_log_event",
    "print_run_statistics",
    "print_step_result",
    "read_session_ids",
    "render_log_event",
    "resolve_editor",
    "role_label",
    "role_model",
    "run_id_from_text",
    "set_pty_no_echo",
    "stamp",
    "truncate",
]


def _handle_gate_menu(
    monitor: LiveMonitor,
    state_dir: str,
    master_fd: int | None,
    forward_pause: threading.Event,
) -> None:
    """Own the wrapper's response to a human-gate menu window on screen.

    The gate's step id is captured synchronously from the state read right
    now — not on a later monitor tick, when a fast answer could already have
    moved current_step_id. The ADR revise feedback gate is answered by the
    wrapper through the terminal editor (and never signals); every other
    gate plays the victory.wav signal for the human.
    """
    state = monitor.read_current_state()
    monitor.gate.open(state)
    if is_feedback_gate((state or {}).get("current_step_id")):
        # The ADR revise feedback gate: the wrapper owns the answer.
        # feedback.md is created (never overwritten) and opened in the
        # terminal editor; on editor close the gate is answered with
        # `continue` so the workflow continues (adr-revise reads
        # feedback.md). If no editor can run, the gate stays interactive for
        # manual input. No victory sound is played for this gate in any path.
        if master_fd is not None:
            open_feedback_editor(
                Path.cwd() / state_dir / "tasks" / "current" / "feedback.md",
                forward_pause,
                master_fd,
            )
    else:
        # The human is needed: play the same signal used for a finished run
        # (success or failure alike).
        notify()


def _consume_output(
    proc: subprocess.Popen,
    monitor: LiveMonitor,
    state_dir: str,
    master_fd: int | None,
    forward_pause: threading.Event,
) -> str:
    """Read specify's stdout until EOF, echoing it timestamped and handling gates.

    Echo of the menu lines themselves is unchanged: every line prints as-is.
    Returns the run id parsed from specify's final "Run ID:" line ("" if the
    line never appeared); the run id is also stored on the monitor so late
    state reads can locate the run directory.
    """
    run_id = ""
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        if is_gate_menu_opener(line):
            _handle_gate_menu(monitor, state_dir, master_fd, forward_pause)
        print(f"[{stamp()}] {line}", flush=True)
        if not run_id:
            run_id = run_id_from_text(line)
            if run_id:
                monitor.run_id = run_id
    return run_id


def _finalize_run(
    proc: subprocess.Popen,
    monitor: LiveMonitor,
    run_id: str,
    t0: float,
    state_dir: str,
    master_fd: int | None,
    forward_thread: threading.Thread | None,
    forward_stop: threading.Event,
) -> int:
    """Stop forwarding and the monitor, reap specify, and report the outcome.

    Runs on every completion path (including when the read loop raised):
    reaping the child even then keeps proc.returncode set, so the failure
    message never prints "exit None". Returns the run's exit code after
    printing the failure message, the resume command, the statistics block
    and the victory signal — none of the reporting ever changes the exit
    code.
    """
    # Stop stdin forwarding and release the pty before reaping the child:
    # the forward thread would otherwise keep writing into the pty while the
    # wrapper exits.
    forward_stop.set()
    if master_fd is not None:
        assert forward_thread is not None
        forward_thread.join(timeout=1)
        with contextlib.suppress(OSError):
            os.close(master_fd)
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
    if run_id or monitor.run_id:
        time.sleep(0.2)
        monitor.finish()
    rc = proc.returncode
    if rc is None:
        rc = 1
    if rc != 0:
        print()
        print(f"[{stamp()}] run failed (exit {rc})")
        if run_id or monitor.run_id:
            print(
                f"[{stamp()}] resume with: specify workflow resume {run_id or monitor.run_id}"
            )
    # The statistics block prints on every completion path and never fails:
    # missing session data or a failed `opencode export` degrade to zeros.
    print_run_statistics(Path.cwd() / state_dir, t1 - t0)
    # One victory.wav signal for every event: gate open, success, failure.
    notify()
    return rc


def main() -> int:
    argv = sys.argv[1:]
    cli_backend: str | None = None
    if argv and argv[0] == "--backend":
        # A leading global flag (spec-run puts it in front of the workflow
        # source): overrides the configured backend for this run.
        if len(argv) < 2:
            print("error: --backend requires a value (opencode or cursor)", file=sys.stderr)
            return 1
        cli_backend = argv[1]
        if cli_backend not in BACKENDS:
            print(
                f"error: invalid --backend value '{cli_backend}'; use 'opencode' or 'cursor'",
                file=sys.stderr,
            )
            return 1
        argv = argv[2:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    source = argv[0]
    extra = argv[1:]

    # Map the installed config + argv to the specify invocation; main() only
    # orchestrates the live run from the result. CONFIG_PATH is passed
    # explicitly so a runtime override of this module's CONFIG_PATH (e.g. by
    # tests) is honored by the config read.
    cfg = load_config(CONFIG_PATH)
    specify_cmd, env, state_dir, logs_dir = build_specify_invocation(
        cfg, source, extra, cli_backend
    )

    run_state_dir = Path.cwd() / ".specify"
    # Snapshot the existing run directories BEFORE the workflow starts: the
    # run id is only printed by specify after the run finishes, so the
    # monitor recognizes the current run as the run dir that appears now.
    prior_runs = existing_run_ids(run_state_dir)
    monitor = LiveMonitor(run_state_dir, prior_runs, logs_dir)
    # Wall-clock run time is measured directly around the child process; it
    # covers every completion path (success, failure, abort).
    t0 = time.monotonic()

    proc, master_fd, forward_pause, forward_stop, forward_thread = _spawn_specify(
        specify_cmd, env
    )
    monitor.start()
    run_id = ""
    try:
        run_id = _consume_output(proc, monitor, state_dir, master_fd, forward_pause)
    finally:
        rc = _finalize_run(
            proc, monitor, run_id, t0, state_dir, master_fd, forward_thread, forward_stop
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
