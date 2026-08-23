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
on failure; the sound and the statistics never change the exit code. The
sound is configured through the `sound:` section of the installed config
(enable/disable the alert, or point it at a custom sound file; ADR-0018).

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

Usage and the `--backend` flag: see wrapper_cli.USAGE (the command
surface lives in wrapper_cli.py, one canonical copy — -h/--help print it).

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
chain in editor.py), the pty plumbing in pty_spawn.py, the CLI surface in
wrapper_cli.py, the engine-stdout consumption policy in stdout_reader.py and
the run teardown/outcome reporting in run_finish.py. This module owns
the main() orchestration flow and re-exports every public name so the
wrapper keeps its single import surface.
"""

from __future__ import annotations

import sys
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
    sound_settings,
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
from notify import SOUND_FILE, configure_sound, play_signal
from pty_spawn import (
    forward_terminal_input,
    set_pty_no_echo,
    spawn_specify,
    stop_forwarding,
)
from run_finish import finalize_run
from run_id_discoverer import RunIdDiscoverer
from run_state import existing_run_ids
from run_statistics import (
    collect_usage,
    export_session_info,
    print_run_statistics,
    read_session_ids,
)
from stdout_reader import consume_output, handle_gate_menu
from step_result_poller import StepResultPoller
from table_format import step_width_for
from workflow_info import workflow_all_step_ids, workflow_step_ids
from wrapper_cli import parse_cli

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
    "configure_sound",
    "consume_output",
    "create_feedback_file",
    "effective_backend",
    "existing_run_ids",
    "export_session_info",
    "extract_numbered_questions",
    "finalize_run",
    "fmt_duration",
    "fmt_minutes",
    "fmt_thousands",
    "forward_terminal_input",
    "handle_gate_menu",
    "is_engine_error",
    "is_engine_header",
    "is_engine_step_start",
    "is_feedback_gate",
    "is_gate_menu_opener",
    "load_config",
    "normalize_config",
    "open_feedback_editor",
    "parse_cli",
    "play_signal",
    "print_run_statistics",
    "questions_source_file",
    "read_session_ids",
    "resolve_editor",
    "resolve_feedback_editor",
    "role_model",
    "run_id_from_text",
    "set_pty_no_echo",
    "sound_settings",
    "spawn_specify",
    "stamp",
    "step_output_rows",
    "step_width_for",
    "stop_forwarding",
    "workflow_all_step_ids",
    "workflow_step_ids",
]


def main() -> int:
    parsed = parse_cli(sys.argv[1:])
    if isinstance(parsed, int):
        return parsed
    cli_backend, source, extra = parsed

    # Map the installed config + argv to the specify invocation; main() only
    # orchestrates the live run from the result. CONFIG_PATH is passed
    # explicitly so a runtime override of this module's CONFIG_PATH (e.g. by
    # tests) is honored by the config read.
    cfg = load_config(CONFIG_PATH)
    # The sound section is validated before the run starts (ADR-0018): an
    # invalid sound setting aborts with an explanation, not a silent degrade.
    try:
        sound_enabled, sound_file = sound_settings(cfg, CONFIG_PATH)
    except ValueError as exc:
        print(f"error: invalid sound config: {exc}", file=sys.stderr)
        return 1
    configure_sound(sound_enabled, sound_file)
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
        proc, master_fd, forward_pause, forward_stop, forward_thread = spawn_specify(
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
        run_id = consume_output(proc, monitor, state_dir, master_fd, forward_pause)
    finally:
        rc = finalize_run(
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
