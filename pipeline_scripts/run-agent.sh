#!/usr/bin/env bash
# run-agent.sh - session glue for the adr-pipeline workflow.
#
# Usage: run-agent.sh <role> "<prompt>" [--task <task-id>] [--reset] [--fork]
#        run-agent.sh <role> --prompt-file <path> [--task <task-id>] [--reset] [--fork]
#
# Keeps one warm agent session per role (stored in <state_dir>/sessions.json)
# and resumes it between workflow steps, so the agent does not re-read the
# project on every step. Two backends, selected by SKLC_BACKEND (exported by
# the run-pipeline.py wrapper; default opencode):
#
#   opencode  -> `opencode run --session <id>|--agent <role> --auto ...`
#   cursor    -> `cursor-agent|agent -p --output-format json --force --trust
#                --model <role-model> [--resume <chatId>] ...`
#
#   --task <id>   scopes the session record (informational, kept for future use)
#   --reset       drop the stored session for the role and start a fresh one
#   --fork        run in an ISOLATED fork of the warm session (ADR-0009): the
#                 prompt executes against a fork that inherits the warm context
#                 but never touches the parent. The fork's id is NOT written to
#                 the session store — the parent id is kept for the next fork.
#                 Backend-specific isolation: opencode forks the warm session
#                 (`opencode run --session <id> --fork`); cursor has no fork
#                 primitive, so each fork invocation mints a fresh chat instead
#                 (see run-agent-cursor.sh).
#
# When --task is omitted, the id is taken from the <state_dir>/tasks/current
# symlink that the workflow's generate-task-id step maintains.
#
# This file is the entry point of a module split, one concern per file: the
# session records and the stale-process cleanup live in session_store.sh
# (sourced), the whole cursor backend in run-agent-cursor.sh (sourced when
# SKLC_BACKEND=cursor) and the @TOKEN@ prompt substitution in
# prompt_subst.sh. This script owns the argv parsing, the task-id
# resolution, the backend dispatch and the opencode branch.
#
# The one-shot task-slug generator used by generate-task-id lives in
# name-task.sh, not here.
#
# Environment:
#   SKLC_STATE_DIR     state directory (default: .workflow relative to cwd)
#   SKLC_ATTACH_FLAG   extra opencode flag, e.g. --attach http://localhost:4096
#                      (set by the run-pipeline.py wrapper from use_serve)
#   SKLC_BACKEND       active backend: opencode (default) or cursor
#   SKLC_PLANNER_MODEL / SKLC_EXECUTOR_MODEL
#                      role model of the active backend (used only by cursor)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
  echo "usage: $0 <role> \"<prompt>\" [--task <task-id>] [--reset] [--fork]" >&2
  echo "       $0 <role> --prompt-file <path> [--task <task-id>] [--reset] [--fork]" >&2
  echo "       role must be 'planner' or 'executor'" >&2
  exit 2
}

[ $# -ge 2 ] || usage
ROLE="$1"
shift
[ "$ROLE" = "planner" ] || [ "$ROLE" = "executor" ] || usage

# Flags are order-independent; --prompt-file is recognized at any position
# (the parallel fan-out calls `planner --fork --prompt-file <path>`).
PROMPT=""
PROMPT_FILE=""
TASK_ID=""
RESET=0
FORK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prompt-file)
      [ $# -ge 2 ] || usage
      PROMPT_FILE="$2"
      shift 2 ;;
    --task)
      [ $# -ge 2 ] || usage
      TASK_ID="$2"
      shift 2 ;;
    --reset)
      RESET=1; shift ;;
    --fork)
      FORK=1; shift ;;
    *)
      # The bare positional prompt is accepted once, anywhere among the flags.
      if [ -z "$PROMPT" ] && [ -z "$PROMPT_FILE" ]; then
        PROMPT="$1"; shift
      else
        usage
      fi ;;
  esac
done
[ -n "$PROMPT" ] || [ -n "$PROMPT_FILE" ] || usage

if [ -n "$PROMPT_FILE" ]; then
  [ -f "$PROMPT_FILE" ] || { echo "error: prompt file not found: $PROMPT_FILE" >&2; exit 2; }
  # Substitute @TOKEN@ placeholders from the environment: the workflow step
  # exports STATE_DIR/LATEST/N/SNAP/etc. before the call, so the prompt files
  # stay plain .md text with no shell or template escapes. The substitution
  # itself lives in prompt_subst.sh, so the prompt format is the only thing
  # that changes that file.
  PROMPT="$("$SCRIPT_DIR/prompt_subst.sh" "$PROMPT_FILE")"
fi

STATE_DIR="${SKLC_STATE_DIR:-.workflow}"
ATTACH_FLAG="${SKLC_ATTACH_FLAG:-}"
BACKEND="${SKLC_BACKEND:-opencode}"

# Raise opencode's per-response output cap (default 32k) so an agent reply
# cannot be truncated mid-reasoning before it acts (ADR-0007). 1000000 is
# effectively unlimited: the provider's own ceiling still applies. Opencode
# only: cursor has its own cap, and the env var is harmless there.
export OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=1000000

# Role model of the active backend (exported by run-pipeline.py): the cursor
# branch passes it to cursor-agent as --model. The env var name is kept next
# to the value (as a literal, not bash 4 case-conversion) for the error below.
if [ "$ROLE" = "planner" ]; then
  ROLE_MODEL="${SKLC_PLANNER_MODEL:-}"
  ROLE_MODEL_VAR="SKLC_PLANNER_MODEL"
else
  ROLE_MODEL="${SKLC_EXECUTOR_MODEL:-}"
  ROLE_MODEL_VAR="SKLC_EXECUTOR_MODEL"
fi

if [ -z "$TASK_ID" ]; then
  # The workflow generates the task id at runtime; recover it from the
  # tasks/current symlink instead of templating the id into every prompt.
  if [ -e "$STATE_DIR/tasks/current" ]; then
    TARGET="$(readlink -f "$STATE_DIR/tasks/current" 2>/dev/null || true)"
    [ -n "$TARGET" ] && TASK_ID="$(basename "$TARGET")"
  fi
fi

if [ -n "$TASK_ID" ] && ! printf '%s' "$TASK_ID" | grep -qE '^[A-Za-z0-9_-]+$'; then
  echo "error: invalid --task value '$TASK_ID'; use only letters, digits, '_' or '-'" >&2
  exit 2
fi

# The session store owns the per-role records, the pid files and the
# stale-agent cleanup (session_store.sh, sourced: it reads the variables
# above and sets SESSIONS_FILE/PID_FILE/LOG_FILE).
source "$SCRIPT_DIR/session_store.sh"
session_paths
if [ "$FORK" -eq 1 ]; then
  # Parallel forks run concurrently (the fan-out's max_concurrency): every
  # invocation needs its OWN log file and pid file, otherwise four processes
  # would truncate the same role log over each other and manage_pid_file's
  # stale-kill would murder a sibling fork mid-run. $$ keeps them unique; the
  # tailer recognizes the -fork-<pid> log names (agent_log_tailer.py).
  LOG_FILE="${LOG_FILE%.jsonl}-fork-$$.jsonl"
  PID_FILE="${PID_FILE%.pid}-fork-$$.pid"
fi
manage_pid_file "$BACKEND"

SESSION_ID=""
if [ "${RESET:-0}" -eq 0 ]; then
  SESSION_ID="$(read_session)"
fi

if [ "$BACKEND" = "cursor" ]; then
  # --- cursor backend: cursor-agent/agent headless with warm chats --------
  # The whole backend lives in run-agent-cursor.sh (sourced on demand): it
  # resolves the binary, mints/resumes warm chats and sets SESSION_ID.
  source "$SCRIPT_DIR/run-agent-cursor.sh"
  run_cursor
else
  # --- opencode backend ----------------------------------------------------
  if [ "$FORK" -eq 1 ] && [ -z "$SESSION_ID" ]; then
    echo "error: --fork requires a stored $ROLE session (no warm session to fork); run the warm-up step first" >&2
    exit 2
  fi
  if [ -z "$SESSION_ID" ]; then
    RC=0
    # Stream opencode into a log file instead of a command substitution: the
    # JSON event stream is large, and capturing it through a pipe made opencode
    # die with SIGPIPE (exit 141) mid-run. A file also keeps a durable per-role
    # log the user can inspect after a failed step.
    opencode run --agent "$ROLE" --auto $ATTACH_FLAG --format json "$PROMPT" > "$LOG_FILE" 2>&1 || RC=$?
    # Nothing is echoed from the event stream to the step's stdout: the
    # workflow runner captures step output through a pipe, and a large stream
    # (dozens of tool calls -> hundreds of KB) made the reader close early,
    # SIGPIPE-ing this script (exit 141). The full log stays in $LOG_FILE.
    if [ "$RC" -ne 0 ]; then
      echo "run-agent: opencode exited $RC; full log: $LOG_FILE" >&2
      exit "$RC"
    fi
    SESSION_ID="$(extract_session_id)"
    if [ -z "$SESSION_ID" ]; then
      echo "error: could not extract a session id from opencode output" >&2
      exit 2
    fi
    save_session "$SESSION_ID"
  else
    RC=0
    FORK_FLAG=""
    if [ "$FORK" -eq 1 ]; then
      FORK_FLAG="--fork"
    fi
    opencode run --session "$SESSION_ID" $FORK_FLAG --agent "$ROLE" --auto $ATTACH_FLAG --format json "$PROMPT" > "$LOG_FILE" 2>&1 || RC=$?
    if [ "$RC" -ne 0 ]; then
      echo "run-agent: opencode exited $RC; full log: $LOG_FILE" >&2
      exit "$RC"
    fi
    # A fork's new session id is deliberately NOT saved: the parent id in the
    # store stays authoritative for the next fork (ADR-0009).
  fi
fi

echo "SESSION:$SESSION_ID"
