#!/usr/bin/env bash
# run-agent.sh - session glue for the adr-pipeline workflow.
#
# Usage: run-agent.sh <role> "<prompt>" [--task <task-id>] [--review-fork <kind>]
#        run-agent.sh <role> --prompt-file <path> [--task <task-id>] [--review-fork <kind>]
#
# Keeps one warm agent session per role (stored in <state_dir>/sessions.json)
# and resumes it between workflow steps, so the agent does not re-read the
# project on every step. Two backends, selected by MO_BACKEND (exported by
# the run-pipeline.py wrapper; default opencode):
#
#   opencode  -> `opencode run --session <id>|--agent <role> --auto ...`
#   cursor    -> `cursor-agent|agent -p --output-format json --force --trust
#                --model <role-model> [--resume <chatId>] ...`
#
#   --task <id>         scopes the session record (informational, kept for
#                       future use)
#   --review-fork <kind> run the prompt in an ISOLATED per-kind fork of the
#                       warm session (ADR-0013, replaces the ADR-0009 --fork):
#                       the FIRST call of a kind forks the warm session and
#                       saves the fork's id in
#                       <state_dir>/sessions-<task-id>-review-<kind>.json;
#                       every later call of the same kind continues that same
#                       fork (`opencode run --session <id>` WITHOUT --fork;
#                       cursor: `--resume <chatId>`), so the reviewer keeps
#                       its past findings across the review-fix-loop
#                       iterations. One fork per review kind
#                       (srp|bugs|review|comment) lives through the whole
#                       loop; the parent warm session is never mutated. If
#                       the saved fork session vanished (opencode
#                       auto-compact/cleanup, "Session not found"), the id is
#                       dropped and the parent is forked again.
#
# When --task is omitted, the id is taken from the <state_dir>/tasks/current
# symlink that the workflow's generate-task-id step maintains.
#
# This file is the entry point of a module split, one concern per file: the
# session records and the stale-process cleanup live in session_store.sh
# (sourced), the whole cursor backend in run-agent-cursor.sh (sourced when
# MO_BACKEND=cursor) and the @TOKEN@ prompt substitution in
# prompt_subst.sh. This script owns the argv parsing, the task-id
# resolution, the backend dispatch and the opencode branch.
#
# The one-shot task-slug generator used by generate-task-id lives in
# name-task.sh, not here.
#
# Environment:
#   MO_STATE_DIR     state directory (default: .workflow relative to cwd)
#   MO_ATTACH_FLAG   extra opencode flag, e.g. --attach http://localhost:4096
#                      (set by the run-pipeline.py wrapper from use_serve)
#   MO_BACKEND       active backend: opencode (default) or cursor
#   MO_PLANNER_MODEL / MO_EXECUTOR_MODEL
#                      role model of the active backend (used only by cursor)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
  echo "usage: $0 <role> \"<prompt>\" [--task <task-id>] [--review-fork <kind>]" >&2
  echo "       $0 <role> --prompt-file <path> [--task <task-id>] [--review-fork <kind>]" >&2
  echo "       role must be 'planner' or 'executor'" >&2
  exit 2
}

[ $# -ge 2 ] || usage
ROLE="$1"
shift
[ "$ROLE" = "planner" ] || [ "$ROLE" = "executor" ] || usage

# Flags are order-independent; --prompt-file is recognized at any position
# (the parallel fan-out calls `planner --review-fork <kind> --prompt-file
# <path>`).
PROMPT=""
PROMPT_FILE=""
TASK_ID=""
REVIEW_FORK=""
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
    --review-fork)
      [ $# -ge 2 ] || usage
      REVIEW_FORK="$2"
      shift 2 ;;
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

STATE_DIR="${MO_STATE_DIR:-.workflow}"
ATTACH_FLAG="${MO_ATTACH_FLAG:-}"
BACKEND="${MO_BACKEND:-opencode}"

# Raise opencode's per-response output cap (default 32k) so an agent reply
# cannot be truncated mid-reasoning before it acts (ADR-0007). 1000000 is
# effectively unlimited: the provider's own ceiling still applies. Opencode
# only: cursor has its own cap, and the env var is harmless there.
export OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=1000000

# Role model of the active backend (exported by run-pipeline.py): the cursor
# branch passes it to cursor-agent as --model. The env var name is kept next
# to the value (as a literal, not bash 4 case-conversion) for the error below.
if [ "$ROLE" = "planner" ]; then
  ROLE_MODEL="${MO_PLANNER_MODEL:-}"
  ROLE_MODEL_VAR="MO_PLANNER_MODEL"
else
  ROLE_MODEL="${MO_EXECUTOR_MODEL:-}"
  ROLE_MODEL_VAR="MO_EXECUTOR_MODEL"
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

if [ -n "$REVIEW_FORK" ] && ! printf '%s' "$REVIEW_FORK" | grep -qE '^[A-Za-z0-9_-]+$'; then
  echo "error: invalid --review-fork value '$REVIEW_FORK'; use only letters, digits, '_' or '-'" >&2
  exit 2
fi

# The session store owns the per-role records, the pid files and the
# stale-agent cleanup (session_store.sh, sourced: it reads the variables
# above and sets SESSIONS_FILE/PID_FILE/LOG_FILE). With --review-fork the
# paths point at the per-kind files (ADR-0013); ROLE_SESSIONS_FILE keeps the
# per-role store, whose warm session is forked on the kind's first call.
source "$SCRIPT_DIR/session_store.sh"
session_paths
manage_pid_file "$BACKEND"

SESSION_ID="$(read_session)"

if [ "$BACKEND" = "cursor" ]; then
  # --- cursor backend: cursor-agent/agent headless with warm chats --------
  # The whole backend lives in run-agent-cursor.sh (sourced on demand): it
  # resolves the binary, mints/resumes warm chats and sets SESSION_ID.
  source "$SCRIPT_DIR/run-agent-cursor.sh"
  run_cursor
else
  # --- opencode backend ----------------------------------------------------
  # Stream opencode into a log file instead of a command substitution: the
  # JSON event stream is large, and capturing it through a pipe made opencode
  # die with SIGPIPE (exit 141) mid-run. A file also keeps a durable per-role
  # log the user can inspect after a failed step.
  #
  # The agent runs in the BACKGROUND so its pid can be recorded: the pid file
  # must carry the AGENT's pid (not the shell's), otherwise the stale-process
  # cleanup in manage_pid_file could never match the backend process name.
  # Nothing is echoed from the event stream to the step's stdout: the
  # workflow runner captures step output through a pipe, and a large stream
  # (dozens of tool calls -> hundreds of KB) made the reader close early,
  # SIGPIPE-ing this script (exit 141). The full log stays in $LOG_FILE.
  run_opencode() {
    # $1: opencode args before --agent: "", "--session <id>" or
    # "--session <parent-id> --fork". Leaves the exit status in RC.
    #
    # $1 is deliberately expanded UNQUOTED: bash word-splits the multi-word
    # flag string into separate argv entries ("--session <id> --fork" ->
    # "--session", "<id>", "--fork"), and the empty string of the
    # `run_opencode ""` call vanishes under the same splitting. The missing
    # quotes are load-bearing — do NOT "fix" them to "$1", that would pass
    # the whole string as ONE argument and break every agent call.
    RC=0
    opencode run $1 --agent "$ROLE" --auto $ATTACH_FLAG --format json "$PROMPT" > "$LOG_FILE" 2>&1 &
    AGENT_PID=$!
    record_agent_pid "$AGENT_PID"
    wait "$AGENT_PID" || RC=$?
  }

  RC=0
  AGENT_PID=""
  if [ -n "$SESSION_ID" ]; then
    # Continue the saved session: the role's warm session, or a per-kind
    # review fork — WITHOUT --fork: the fork was created once and is only
    # continued (ADR-0013).
    run_opencode "--session $SESSION_ID"
    if [ "$RC" -ne 0 ]; then
      if [ -n "$REVIEW_FORK" ] && grep -q "Session not found" "$LOG_FILE"; then
        # The per-kind fork session vanished (opencode auto-compact or
        # cleanup): drop the stale id and re-fork the parent below
        # (ADR-0013).
        #
        # The rm is the ONLY "clear" primitive: save_session rewrites the
        # per-kind file but never deletes a key, and the re-fork below
        # always ends in save_session — without the rm this clearing would
        # be undone. And the rm must survive even a FAILED re-fork (the
        # extract-session error exits before save): then the NEXT
        # invocation of this kind sees no id and forks the parent directly
        # instead of retrying the dead session. It is not dead code.
        rm -f "$SESSIONS_FILE"
        SESSION_ID=""
      else
        echo "run-agent: opencode exited $RC; full log: $LOG_FILE" >&2
        exit "$RC"
      fi
    fi
  fi
  if [ -z "$SESSION_ID" ]; then
    if [ -n "$REVIEW_FORK" ]; then
      # First check of this kind — or the re-fork after a vanished session:
      # fork the parent warm session once (ADR-0013). The parent id lives in
      # the per-role store and is never mutated; the fork's own id is saved
      # to the per-kind file.
      PARENT_ID="$(read_session_from "$ROLE_SESSIONS_FILE")"
      if [ -z "$PARENT_ID" ]; then
        echo "error: --review-fork requires a stored $ROLE session (no warm session to fork); run the warm-up step first" >&2
        exit 2
      fi
      run_opencode "--session $PARENT_ID --fork"
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
      # No saved role session yet: a brand-new warm session.
      run_opencode ""
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
    fi
  fi
fi

echo "SESSION:$SESSION_ID"
