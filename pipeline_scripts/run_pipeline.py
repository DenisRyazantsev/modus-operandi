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

Environment:
  SKLC_CONFIG          path of the installed config.yml (default: derived
                       from this wrapper's location)
  SKLC_SCRIPTS_DIR     directory of the installed pipeline scripts (set to
                       this wrapper's own directory for the specify child)
  SKLC_ATTACH_FLAG     opencode attach flag passed to run-agent.sh/name-task.sh
                       (set from workflow.use_serve in the installed config)

This file is the entry point of a small module split (one class per file):
the classes live in run_id_discoverer.py / step_result_poller.py /
agent_log_tailer.py / gate_state.py / buffered_emitter.py / live_monitor.py
and the shared constants and pure helpers in _run_pipeline_common.py. This
module owns the main() orchestration flow and re-exports the class and
helper names so the wrapper keeps its single public surface.
"""

from __future__ import annotations

import contextlib
import json
import os
import pty
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import termios
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
from gate_state import GateState
from live_monitor import LiveMonitor
from run_id_discoverer import RunIdDiscoverer
from step_result_poller import StepResultPoller

# Public surface of the wrapper: the classes and the shared helpers, so tests
# and callers keep a single import target (the run_pipeline module).
__all__ = [
    "AgentLogTailer",
    "BufferedEmitter",
    "GateState",
    "LiveMonitor",
    "RunIdDiscoverer",
    "StepResultPoller",
    "existing_run_ids",
    "fmt_duration",
    "fmt_thousands",
    "is_feedback_gate",
    "is_gate_menu_opener",
    "print_log_event",
    "print_step_result",
    "render_log_event",
    "role_label",
    "run_id_from_text",
    "stamp",
    "truncate",
]

# Absolute path of the victory.wav signal: shipped by the installer next to
# this wrapper, so it is resolved from the wrapper's own location at runtime.
SOUND_FILE = Path(__file__).resolve().parent / "victory.wav"

# The installed config.yml: the only runtime source of the workflow settings
# (state_dir, adr_dir, use_serve, human_gates). `__file__` is the wrapper
# FILE (~/.config/opencode/scripts/run-pipeline.py), so ~/.config is three
# `.parent` hops up from it: scripts/ -> opencode/ -> .config/. SKLC_CONFIG
# overrides the location (used by tests).
CONFIG_PATH = Path(
    os.environ.get("SKLC_CONFIG")
    or (Path(__file__).resolve().parent.parent.parent / "spec-kit-llm-client" / "config.yml")
)


def load_config() -> dict:
    """Read the installed config.yml into a dict, or {} on any failure.

    A missing or unreadable file degrades to the documented defaults, so a
    hand-invoked wrapper (or a config deleted after install) still runs.
    """
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import yaml  # installed by the installer (deps.ensure_pyyaml)

        data = yaml.safe_load(text) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def notify() -> None:
    """Play the single victory.wav signal, for every event.

    Called when a human-gate menu opens (except the ADR revise feedback
    gate, which the wrapper answers itself and never signals), on a
    successful run and on a failed run alike — one sound for all events,
    never different signals. Playback is non-blocking (the player process is
    not waited for) and degrades quietly: no sound file, no system player or
    a non-TTY stdout simply skip the call, so the exit code and the
    wrapper's output are never affected.
    """
    try:
        if not getattr(sys.stdout, "isatty", lambda: False)():
            return
        if not SOUND_FILE.is_file():
            return
        if sys.platform == "darwin":
            player = shutil.which("afplay")
        elif sys.platform.startswith("win"):
            import winsound  # Windows only

            winsound.PlaySound(
                str(SOUND_FILE), winsound.SND_FILENAME | winsound.SND_ASYNC
            )
            return
        else:
            player = shutil.which("paplay") or shutil.which("aplay")
        if not player:
            return
        subprocess.Popen(
            [player, str(SOUND_FILE)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        # Quiet degradation: a sound problem must never fail the run.
        pass


def read_session_ids(state_dir: Path) -> dict[str, str]:
    """Map role -> session id from <state_dir>/sessions-<task-id>.json.

    The task id is taken from the <state_dir>/tasks/current symlink that the
    workflow's generate-task-id step maintains; a missing or broken symlink
    yields no ids (Path.resolve() never raises and always yields a final
    name here, so the sessions-file read below simply fails). Only roles
    with a non-empty id are returned.
    """
    try:
        task_id = (state_dir / "tasks" / "current").resolve().name
        data = json.loads(
            (state_dir / f"sessions-{task_id}.json").read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        role: data[role]
        for role in ("planner", "executor")
        if isinstance(data.get(role), str) and data[role]
    }


def export_session_info(session_id: str) -> dict | None:
    """Return the `info` dict of `opencode export <sessionID>`, or None.

    opencode prints the session export as JSON on stdout ("Exporting
    session: …" goes to stderr). The output is captured into a temporary
    file instead of a pipe: opencode (<= 1.18.x) can exit before its piped
    stdout is fully flushed once the session is larger than the pipe buffer,
    silently truncating the JSON. With a file the full output is available;
    a truncated run usually fails to parse, so the export is retried once.
    Any remaining failure — opencode missing, a non-zero exit, unparseable
    output — returns None and the caller degrades to zero/dash values
    instead of failing the run.
    """
    for _ in range(2):
        try:
            with tempfile.TemporaryFile(mode="w+b") as out:
                result = subprocess.run(
                    ["opencode", "export", session_id],
                    stdout=out,
                    stderr=subprocess.DEVNULL,
                    timeout=120,
                )
                if result.returncode != 0:
                    return None
                out.seek(0)
                try:
                    info = json.loads(out.read().decode("utf-8"))["info"]
                except Exception:
                    continue  # truncated/invalid export: retry once
                return info if isinstance(info, dict) else None
        except Exception:
            return None
    return None


def collect_usage(state_dir: Path) -> dict[str, int | float]:
    """Aggregate token usage and cost across the planner and executor sessions.

    Sums info.tokens.{input,output,reasoning}, info.tokens.cache.{read,write}
    and info.cost of both roles into one dict; a role with no session id or a
    failed export contributes nothing. No live token accumulator is involved:
    opencode reports the full usage of each saved session itself.
    """
    totals: dict[str, int | float] = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost": 0.0,
    }
    for session_id in read_session_ids(state_dir).values():
        info = export_session_info(session_id)
        if info is None:
            continue
        tokens = info.get("tokens")
        if isinstance(tokens, dict):
            totals["input"] += int(tokens.get("input") or 0)
            totals["output"] += int(tokens.get("output") or 0)
            totals["reasoning"] += int(tokens.get("reasoning") or 0)
            cache = tokens.get("cache")
            if isinstance(cache, dict):
                totals["cache_read"] += int(cache.get("read") or 0)
                totals["cache_write"] += int(cache.get("write") or 0)
        cost = info.get("cost")
        if isinstance(cost, (int, float)):
            totals["cost"] += float(cost)
    return totals


def print_run_statistics(state_dir: Path, elapsed: float) -> None:
    """Print the final `=== run statistics ===` block.

    Printed after the run on every completion path (success, failure, abort).
    Token counts use space thousand separators; wall time is HH:MM:SS.
    Missing session data degrades to zeros — the wrapper never fails here.
    """
    usage = collect_usage(state_dir)
    print()
    print("=== run statistics ===")
    print(f"wall time: {fmt_duration(elapsed)}")
    print(
        "tokens: input {} · output {} · reasoning {}".format(
            fmt_thousands(usage["input"]),
            fmt_thousands(usage["output"]),
            fmt_thousands(usage["reasoning"]),
        )
    )
    print(
        "cache: read {} · write {}".format(
            fmt_thousands(usage["cache_read"]),
            fmt_thousands(usage["cache_write"]),
        )
    )
    print("cost: ${:.2f}".format(usage["cost"]))


def resolve_editor() -> list[str] | None:
    """Resolve the terminal editor for the feedback file.

    Order: $VISUAL, then $EDITOR, then nano, then vi. A $VISUAL/$EDITOR
    value may carry arguments (`code --wait`) and is split like a shell
    command line (a malformed value is skipped with a warning, as in the
    launcher); the first candidate whose binary is found on PATH wins. None
    means no editor is available at all and the feedback gate falls back to
    manual input. As in the launcher's `_resolve_editor`, a missing binary
    falls through to the next candidate and a fully empty chain is reported
    as None.
    """
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var)
        if not value:
            continue
        try:
            cmd = shlex.split(value)
        except ValueError as exc:
            print(
                f"warning: {var} is malformed ({exc}); skipping it",
                file=sys.stderr,
            )
            continue
        if cmd and shutil.which(cmd[0]):
            return cmd
    for name in ("nano", "vi"):
        if shutil.which(name):
            return [name]
    return None


def create_feedback_file(path: Path) -> None:
    """Create the empty feedback.md for the revise gate.

    Never overwrites an existing file: the planner may have written one, or
    the user may have started writing during an earlier fallback.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()


def open_feedback_editor(
    feedback_path: Path, pause: threading.Event, master_fd: int
) -> bool:
    """Own the ADR revise feedback gate.

    Pauses stdin forwarding, creates feedback.md (never overwriting), opens
    it in the terminal editor (which inherits the real terminal, not the
    pty, so there is no race with the gate's input()) and, on editor close,
    answers the gate with `continue` so the workflow continues (adr-revise
    reads feedback.md). Returns True when the wrapper answered the gate;
    False on fallback — no TTY or no editor on PATH — where the file is
    still created, forwarding is left running and the gate stays interactive
    for manual input.
    """
    create_feedback_file(feedback_path)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    editor = resolve_editor()
    if editor is None:
        return False
    pause.set()
    try:
        try:
            subprocess.run([*editor, str(feedback_path)], check=False)
        except OSError as exc:
            print(
                f"error: cannot start editor {editor[0]}: {exc}",
                file=sys.stderr,
            )
            return False
        # "continue" is the option declared on the adr-feedback-gate step
        # (options: [continue, abort] in the installed adr-pipeline.yml); the
        # wrapper hardcodes it because it has no parsed handle on the
        # workflow's options, so this string is a cross-file contract, not a
        # free-form answer — a mismatch makes specify reject it and the gate
        # silently degrades to manual input. The answer is written while
        # forwarding is still paused: it is guaranteed to be the first thing
        # the gate's input() reads.
        with contextlib.suppress(OSError):
            os.write(master_fd, b"continue\n")
        return True
    finally:
        pause.clear()


def forward_terminal_input(
    source, master_fd: int, pause: threading.Event, stop: threading.Event
) -> None:
    """Forward terminal input to specify's pty stdin.

    Runs in a background thread while specify runs; the main thread pauses
    it (pause.set()) while the feedback editor is open so the user's
    keystrokes reach only the editor. Exits on terminal EOF or when stop is
    set.
    """
    while not stop.is_set():
        if pause.is_set():
            time.sleep(0.05)
            continue
        try:
            readable, _, _ = select.select([source], [], [], 0.1)
        except (OSError, ValueError):
            return
        if not readable:
            continue
        try:
            line = source.readline()
        except (OSError, ValueError):
            return
        if not line:
            return  # terminal EOF: nothing more to forward
        try:
            os.write(master_fd, line.encode("utf-8"))
        except (OSError, ValueError):
            return


def set_pty_no_echo(fd: int) -> None:
    """Disable ECHO on the pty slave (best effort).

    The user already sees their keystrokes echoed by the real terminal; a
    pty-side ECHO would only accumulate echoed bytes in the master's read
    buffer. termios failure leaves the pty at its defaults.
    """
    try:
        attrs = termios.tcgetattr(fd)
        # tcgetattr returns a 7-element list; index 3 is the local-flags
        # field (lflag), where ECHO/ECHONL live — clearing them there stops
        # the pty from echoing, without touching the other modes.
        attrs[3] &= ~(termios.ECHO | termios.ECHONL)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (OSError, ValueError):
        pass


def build_specify_invocation(
    cfg: dict, source: str, extra: list[str]
) -> tuple[list[str], dict[str, str], str, Path]:
    """Map the installed config + argv to the specify invocation.

    The single place that turns config.yml into the launch of specify;
    returns (specify_cmd, env, state_dir, logs_dir) so main() only
    orchestrates the live run. No run-side I/O happens here:

    - state_dir/adr_dir go to the workflow as -i inputs (its steps reference
      {{ inputs.state_dir }} / {{ inputs.adr_dir }});
    - use_serve becomes the SKLC_ATTACH_FLAG env var for
      run-agent.sh/name-task.sh;
    - human_gates decides whether the ADR gate's verdict input is passed as
      empty (interactive) or left to its "approve" default (auto-approve);
    - run-agent.sh keeps its sessions/logs/pids under the same state dir the
      workflow steps write artifacts to, so it must see SKLC_STATE_DIR.
    """
    workflow = cfg.get("workflow") or {}
    state_dir = workflow.get("state_dir") or ".workflow"
    adr_dir = workflow.get("adr_dir") or "architecture"
    use_serve = bool(workflow.get("use_serve", False))
    human_gates = bool(workflow.get("human_gates", True))
    attach_flag = "--attach http://localhost:4096" if use_serve else ""
    scripts_dir = str(Path(__file__).resolve().parent)
    env = dict(os.environ)
    env["SKLC_SCRIPTS_DIR"] = scripts_dir
    env["SKLC_ATTACH_FLAG"] = attach_flag
    env["SKLC_STATE_DIR"] = state_dir

    specify_cmd = [
        "specify",
        "workflow",
        "run",
        source,
        "-i",
        f"state_dir={state_dir}",
        "-i",
        f"adr_dir={adr_dir}",
    ]
    if human_gates:
        # Interactive gates: an empty adr_verdict falls through to the human
        # prompt. Non-interactive runs omit it, so the declared default
        # "approve" auto-approves the ADR gate (matching human_gates: false).
        specify_cmd += ["-i", "adr_verdict="]
    specify_cmd += extra

    logs_dir = Path.cwd() / state_dir / "logs"
    return specify_cmd, env, state_dir, logs_dir


def _spawn_specify(
    specify_cmd: list[str], env: dict[str, str]
) -> tuple[
    subprocess.Popen, int | None, threading.Event, threading.Event, threading.Thread | None
]:
    """Spawn specify and own its stdin plumbing; returns the live run parts.

    The wrapper owns specify's stdin only on a terminal run: a pty keeps
    sys.stdin.isatty() True inside specify (its gate step goes PAUSED on a
    non-TTY stdin, see ADR-0002), so interactive gates prompt as before
    while the wrapper can still inject the feedback-gate answer itself. On a
    non-TTY run specify keeps the inherited stdin (also non-TTY), so gates
    go PAUSED and no "┌─ Gate" menu is drawn — exactly the documented
    non-interactive behavior.

    Returns (proc, master_fd, forward_pause, forward_stop, forward_thread);
    on a non-TTY run master_fd and forward_thread are None.
    """
    master_fd: int | None = None
    forward_pause = threading.Event()
    forward_stop = threading.Event()
    forward_thread: threading.Thread | None = None
    if sys.stdin.isatty():
        master_fd, slave_fd = pty.openpty()
        set_pty_no_echo(slave_fd)
        proc = subprocess.Popen(
            specify_cmd,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        os.close(slave_fd)
        forward_thread = threading.Thread(
            target=forward_terminal_input,
            args=(sys.stdin, master_fd, forward_pause, forward_stop),
            daemon=True,
        )
        forward_thread.start()
    else:
        proc = subprocess.Popen(
            specify_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    return proc, master_fd, forward_pause, forward_stop, forward_thread


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
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    source = argv[0]
    extra = argv[1:]

    # Map the installed config + argv to the specify invocation; main() only
    # orchestrates the live run from the result.
    cfg = load_config()
    specify_cmd, env, state_dir, logs_dir = build_specify_invocation(cfg, source, extra)

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
