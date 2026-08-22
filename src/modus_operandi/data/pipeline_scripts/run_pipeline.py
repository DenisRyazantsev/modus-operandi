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
wrapper can answer the feedback gate itself. When that gate opens
the wrapper creates <state_dir>/tasks/current/feedback.md (never overwriting
an existing file), opens it in the terminal editor ($VISUAL, then $EDITOR,
then nano, then vi), and on editor close answers the gate with `continue` so
the workflow resumes (study-revise reads feedback.md). If no editor can run
(non-TTY or none found), the file is still created and the gate stays
interactive for manual input. On a non-TTY run no pty is used and specify
keeps the inherited stdin, so gates keep going PAUSED exactly as before.

When the run finishes (success, failure or abort alike) the wrapper prints a
`=== run statistics ===` block: the wall-clock run time and the token/cost
usage of the planner and executor (opencode: exported by session id; cursor:
summed from the per-turn usage fields of the agent logs, cost n/a),
followed by a per-stage latency table (ADR-0009) built from the run's
log.jsonl (stage durations, agent-call vs shell-overhead breakdown, and the
parallel-checks detail for the review fan-out). It also plays a single
victory.wav signal on gate-open (except the feedback gate), on success and
on failure; the sound and the statistics never change the exit code.

Every log line is one aligned table row (ADR-0016):
`[hh:mm:ss] [<role>] <spin> [<step> N/M] <tokens>`. Agent logs are no
longer echoed (ADR-0011): instead each active process — a role, or a
role+fork for the parallel review forks — shows one row with the
cumulative token/cost sums from the agent-log events (ADR-0012/0013:
opencode `step_finish`, cursor result events with usage), and while a step
has no agent events yet a synthesized `[harness]` row with a 0.25
s-cadence spinner is shown, so the status is visible on every step from
the moment it starts. The role and step columns are aligned to their
widest labels, computed from the workflow file before the run (every step
id, nested included, sizes the step column); the token sub-columns
right-align and grow with the widest value seen during the run, and
already-printed rows are never re-rendered. The block is redrawn in place
on a TTY; on a non-TTY the same aligned rows print without the spinner,
and no heartbeat lines ever go into a log. The rows are fixed (kept as
history) when a step completes; only rows appended during the current run
are counted (pre-existing log files are baselined at startup). A step's
final agent events accumulate before the step's captured output rows:
captured stdout/stderr of finished steps and engine diagnostics print as
`[harness]` rows with an empty step column (`SESSION:` lines are dropped).

Usage: run-pipeline.py <workflow-id-or-path> [extra specify args...]
  run-pipeline.py review-pipeline
  run-pipeline.py task-pipeline -i task="..."
  run-pipeline.py ~/.config/modus-operandi/review-pipeline.yml -i branch-diff=true
  run-pipeline.py --backend cursor task-pipeline -i task="..."   # backend override

Environment:
  MO_CONFIG          path of the installed config.yml (default: derived
                       from this wrapper's location)
  MO_SCRIPTS_DIR     directory of the installed pipeline scripts (set to
                       this wrapper's own directory for the specify child)
  MO_ATTACH_FLAG     opencode attach flag passed to run-agent.sh/name-task.sh
                       (set from workflow.use_serve in the installed config)

The wrapper also computes the effective backend for the run (a leading
`--backend <opencode|cursor>` CLI flag wins over the `backend:` config key,
which defaults to opencode) and exports it to the workflow steps through
MO_BACKEND plus the role models of the active backend through
MO_PLANNER_MODEL / MO_EXECUTOR_MODEL (run-agent.sh/name-task.sh read
them; the opencode branch ignores the models - the agent files carry them).

This file is the entry point of a module split, one concern per file: the
live-monitor classes live in run_id_discoverer.py / step_result_poller.py /
agent_log_tailer.py / gate_state.py / buffered_emitter.py / live_monitor.py,
the engine-stdout grammar in engine_output.py, the feedback-gate domain in
feedback_gate.py, the display/formatting helpers in display.py, the run-state
observation in run_state.py and the workflow-file introspection in
workflow_info.py; the config-to-invocation mapping in config_invocation.py,
the run statistics in run_statistics.py, the victory.wav policy in notify.py,
the feedback gate's editor interaction in feedback_editor.py (with the editor
chain in editor.py) and the pty plumbing in pty_spawn.py. This module owns
the main() orchestration flow and re-exports every public name so the
wrapper keeps its single import surface.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

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
from display import (
    fmt_duration,
    fmt_minutes,
    fmt_thousands,
    stamp,
    step_output_rows,
)
from editor import resolve_editor, resolve_feedback_editor
from engine_output import (
    is_engine_error,
    is_engine_header,
    is_engine_step_start,
    is_gate_menu_opener,
    run_id_from_text,
)
from feedback_editor import create_feedback_file, open_feedback_editor
from feedback_gate import extract_numbered_questions, is_feedback_gate, questions_source_file
from gate_state import GateState
from live_lines import LiveLines
from live_monitor import LiveMonitor
from notify import SOUND_FILE, notify
from pty_spawn import _spawn_specify, forward_terminal_input, set_pty_no_echo
from run_id_discoverer import RunIdDiscoverer
from run_state import existing_run_ids
from run_statistics import (
    collect_usage,
    export_session_info,
    print_run_statistics,
    read_session_ids,
)
from step_result_poller import StepResultPoller
from table_format import step_width_for
from workflow_info import workflow_all_step_ids, workflow_step_ids

# Public surface of the wrapper: the classes and the helper functions, so
# tests and callers keep a single import target (the run_pipeline module).
__all__ = [
    "AgentLogTailer",
    "BufferedEmitter",
    "GateState",
    "LiveLines",
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
    "extract_numbered_questions",
    "fmt_duration",
    "fmt_minutes",
    "fmt_thousands",
    "forward_terminal_input",
    "is_engine_error",
    "is_engine_header",
    "is_engine_step_start",
    "is_feedback_gate",
    "is_gate_menu_opener",
    "load_config",
    "normalize_config",
    "notify",
    "open_feedback_editor",
    "print_run_statistics",
    "questions_source_file",
    "read_session_ids",
    "resolve_editor",
    "resolve_feedback_editor",
    "role_model",
    "run_id_from_text",
    "set_pty_no_echo",
    "stamp",
    "step_output_rows",
    "step_width_for",
    "workflow_all_step_ids",
    "workflow_step_ids",
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
        notify()


def _consume_output(
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
            _handle_gate_menu(monitor, state_dir, master_fd, forward_pause)
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


def _stop_forwarding(
    master_fd: int | None,
    forward_stop: threading.Event,
    forward_thread: threading.Thread | None,
) -> None:
    """Stop stdin forwarding and release the pty before reaping the child.

    The forward thread would otherwise keep writing into the pty while the
    wrapper exits, so it is stopped and joined first; the master fd is
    closed best-effort (a pty-less non-TTY run passes None for both).
    """
    forward_stop.set()
    if master_fd is not None:
        assert forward_thread is not None
        forward_thread.join(timeout=1)
        with contextlib.suppress(OSError):
            os.close(master_fd)


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
    # failure alike. (The gate-open signal is played in _handle_gate_menu;
    # the "one signal for every event" policy is stated in the module
    # docstring, where the whole signal surface is visible.)
    notify()


def _finalize_run(
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
    _stop_forwarding(master_fd, forward_stop, forward_thread)
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


def _parse_cli(argv: list[str]) -> tuple[str | None, str, list[str]] | int:
    """Parse the wrapper's argv into (cli_backend, source, extra), or an exit code.

    The optional leading `--backend <opencode|cursor>` flag is validated
    and consumed before the workflow source; the remaining argv is the
    source plus the extra specify args. An unusable invocation prints its
    message here and returns the exit code: empty argv and -h/--help print
    the usage (0), a bad --backend prints the error (1). CLI surface
    changes stay in this one function, away from the orchestration body.
    """
    cli_backend: str | None = None
    if argv and argv[0] == "--backend":
        # A leading global flag (modus-operandi puts it in front of the workflow
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
    return cli_backend, argv[0], argv[1:]


def main() -> int:
    parsed = _parse_cli(sys.argv[1:])
    if isinstance(parsed, int):
        return parsed
    cli_backend, source, extra = parsed

    # Map the installed config + argv to the specify invocation; main() only
    # orchestrates the live run from the result. CONFIG_PATH is passed
    # explicitly so a runtime override of this module's CONFIG_PATH (e.g. by
    # tests) is honored by the config read.
    cfg = load_config(CONFIG_PATH)
    backend = effective_backend(cfg, cli_backend)
    specify_cmd, env, state_dir, logs_dir = build_specify_invocation(
        cfg, source, extra, cli_backend
    )

    run_state_dir = Path.cwd() / ".specify"
    # Snapshot the existing run directories BEFORE the workflow starts: the
    # run id is only printed by specify after the run finishes, so the
    # monitor recognizes the current run as the run dir that appears now.
    prior_runs = existing_run_ids(run_state_dir)
    # The ordered top-level step ids of the workflow file drive the N/M
    # progress; a missing/unreadable file degrades to None and the progress
    # is omitted (ADR-0011). The aligned step column of the log rows is
    # sized from every step id of the workflow file (nested included), so
    # the widest loop/fan-out bracket fits from the start; a runtime step
    # id wider than the static width widens the column for the rest of the
    # run (ADR-0016).
    step_ids = workflow_step_ids(source)
    all_step_ids = workflow_all_step_ids(source)
    step_width = step_width_for(all_step_ids, len(step_ids) if step_ids else 0)
    # The backend reaches the live lines through the monitor: on cursor the
    # price is omitted (no cost reported), on opencode it is shown
    # (ADR-0012).
    monitor = LiveMonitor(
        run_state_dir,
        prior_runs,
        logs_dir,
        step_ids=step_ids,
        backend=backend,
        step_width=step_width,
    )
    # Wall-clock run time is measured directly around the child process; it
    # covers every completion path (success, failure, abort).
    t0 = time.monotonic()

    try:
        proc, master_fd, forward_pause, forward_stop, forward_thread = _spawn_specify(
            specify_cmd, env
        )
    except OSError as exc:
        # The prerequisites check does not verify `specify` (only the dev
        # install flow's syntax probe does): a missing binary must surface
        # as a one-line error, not a Python traceback.
        print(f"error: cannot run specify: {exc}", file=sys.stderr)
        return 1
    monitor.start()
    run_id = ""
    try:
        run_id = _consume_output(proc, monitor, state_dir, master_fd, forward_pause)
    finally:
        rc = _finalize_run(
            proc,
            monitor,
            run_id,
            t0,
            state_dir,
            master_fd,
            forward_thread,
            forward_stop,
            backend,
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
