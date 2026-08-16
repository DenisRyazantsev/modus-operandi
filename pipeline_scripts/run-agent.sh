#!/usr/bin/env bash
# run-agent.sh - session glue for the adr-pipeline workflow.
#
# Usage: run-agent.sh <role> "<prompt>" [--task <task-id>] [--reset]
#        run-agent.sh <role> --prompt-file <path> [--task <task-id>] [--reset]
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
#
# When --task is omitted, the id is taken from the <state_dir>/tasks/current
# symlink that the workflow's generate-task-id step maintains.
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

usage() {
  echo "usage: $0 <role> \"<prompt>\" [--task <task-id>] [--reset]" >&2
  echo "       $0 <role> --prompt-file <path> [--task <task-id>] [--reset]" >&2
  echo "       role must be 'planner' or 'executor'" >&2
  exit 2
}

[ $# -ge 2 ] || usage
ROLE="$1"
if [ "${2:-}" = "--prompt-file" ]; then
  [ $# -ge 3 ] || usage
  PROMPT_FILE="$3"
  [ -f "$PROMPT_FILE" ] || { echo "error: prompt file not found: $PROMPT_FILE" >&2; exit 2; }
  # Substitute @TOKEN@ placeholders from the environment: the workflow step
  # exports STATE_DIR/LATEST/N/SNAP/etc. before the call, so the prompt files
  # stay plain .md text with no shell or template escapes.
  PROMPT="$(python3 - "$PROMPT_FILE" <<'PYEOF'
import os
import re
import sys
text = open(sys.argv[1], encoding="utf-8").read()
sys.stdout.write(re.sub(r"@([A-Z0-9_]+)@", lambda m: os.environ.get(m.group(1), m.group(0)), text))
PYEOF
)"
  shift 3
else
  PROMPT="$2"
  shift 2
fi
[ "$ROLE" = "planner" ] || [ "$ROLE" = "executor" ] || usage

TASK_ID=""
RESET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --task) [ $# -ge 2 ] || usage; TASK_ID="$2"; shift 2 ;;
    --reset) RESET=1; shift ;;
    *) usage ;;
  esac
done

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
if [ -n "$TASK_ID" ]; then
  SESSIONS_FILE="$STATE_DIR/sessions-$TASK_ID.json"
else
  SESSIONS_FILE="$STATE_DIR/sessions.json"
fi
PID_FILE="$STATE_DIR/pids/$(basename "$SESSIONS_FILE").$ROLE.pid"
LOG_DIR="$STATE_DIR/logs"
LOG_FILE="$LOG_DIR/$(basename "$SESSIONS_FILE" .json)-$ROLE.jsonl"

mkdir -p "$STATE_DIR/pids" "$LOG_DIR"
if ! touch "$SESSIONS_FILE"; then
  echo "error: cannot write $SESSIONS_FILE" >&2
  exit 2
fi

# Kill any agent process left over from a previously killed step (e.g. a
# shell-step timeout that killed the shell but not the agent), so a zombie
# cannot keep writing to this session or burn tokens. The process name to
# match depends on the backend: opencode vs cursor-agent/agent.
if [ "$BACKEND" = "cursor" ]; then
  STALE_PROC_PATTERN='^(cursor-agent|agent)$'
else
  STALE_PROC_PATTERN='^opencode'
fi
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    if ps -p "$OLD_PID" -o comm= 2>/dev/null | grep -qE "$STALE_PROC_PATTERN"; then
      echo "warning: killing stale $BACKEND process $OLD_PID for role '$ROLE'" >&2
      kill "$OLD_PID" 2>/dev/null || true
    fi
  fi
  rm -f "$PID_FILE"
fi
echo "$$" > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT

read_session() {
  python3 -c 'import json,sys
p, r = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(p))
    sys.stdout.write(d.get(r, ""))
except Exception:
    pass' "$SESSIONS_FILE" "$ROLE"
}

save_session() {
  python3 -c 'import json,sys
p, r, i = sys.argv[1], sys.argv[2], sys.argv[3]
d = {}
try:
    d = json.load(open(p))
except Exception:
    pass
d[r] = i
with open(p, "w") as f:
    json.dump(d, f, indent=2)' "$SESSIONS_FILE" "$ROLE" "$1"
}

extract_session_id() {
  # Read the session id straight from the log file with python instead of
  # piping sed into head: on a large log sed is still writing matches when
  # head has already exited, gets SIGPIPE, and with set -o pipefail the
  # whole script dies with exit 141. The regex covers opencode's "sessionID"
  # and cursor's "session_id" JSON fields alike.
  python3 -c 'import re, sys
m = re.search(rb"\"session[_]?[iI][dD]\":\"([^\"]*)\"", open(sys.argv[1], "rb").read())
if m:
    sys.stdout.write(m.group(1).decode())' "$LOG_FILE"
}

resolve_cursor_binary() {
  # The specific `cursor-agent` name is probed FIRST because it is
  # unambiguous: a bare `agent` on PATH may be an unrelated binary (Cursor
  # documents `agent` as its CLI entrypoint and ships `cursor-agent` as a
  # backward-compatible alias, but other tools install an `agent` too).
  # `agent` is therefore only the fallback, and the name actually found is
  # used for the invocation and for the stale process matching.
  if command -v cursor-agent >/dev/null 2>&1; then
    echo "cursor-agent"
    return 0
  fi
  if command -v agent >/dev/null 2>&1; then
    echo "agent"
    return 0
  fi
  return 1
}

role_body_file() {
  # The role body (the same PLANNER_BODY/EXECUTOR_BODY the installer writes
  # into the opencode agent files) lives next to this script as plain text;
  # cursor has no agent files, so the body prefixes the FIRST message of a
  # fresh chat and the model remembers its role from then on.
  local file
  file="$(dirname "$0")/$ROLE-body.txt"
  if [ ! -f "$file" ] && [ -n "${SKLC_SCRIPTS_DIR:-}" ]; then
    file="$SKLC_SCRIPTS_DIR/$ROLE-body.txt"
  fi
  if [ -f "$file" ]; then
    echo "$file"
    return 0
  fi
  return 1
}

extract_chat_id() {
  # Parse the `create-chat` output into a chat id: the CLI prints the id as
  # plain text or as a JSON object; empty input prints nothing. The cursor
  # CLI is in beta and `create-chat`'s output key is undocumented and
  # changes between versions, so every plausible key is parsed defensively
  # instead of breaking on a rename.
  python3 -c 'import json,sys
s = sys.stdin.read().strip()
if not s:
    sys.exit(1)
if s.startswith("{"):
    try:
        d = json.loads(s)
        for k in ("chat_id", "chatId", "id", "session_id", "sessionId"):
            if d.get(k):
                print(d[k])
                sys.exit(0)
    except Exception:
        pass
print(s)'
}

cursor_run() {
  # One headless cursor-agent invocation for the current turn; `--resume` is
  # added only when a saved chat id exists. Nothing is echoed from the JSON
  # stream to the step's stdout: the workflow runner captures step output
  # through a pipe, and a large stream made the reader close early,
  # SIGPIPE-ing this script (exit 141). The full log stays in $LOG_FILE.
  local rc=0
  if [ -n "$SESSION_ID" ]; then
    "$CURSOR_BIN" -p --output-format json --force --trust --workspace "$(pwd)" --model "$ROLE_MODEL" --resume "$SESSION_ID" "$PROMPT_FULL" > "$LOG_FILE" 2>&1 || rc=$?
  else
    "$CURSOR_BIN" -p --output-format json --force --trust --workspace "$(pwd)" --model "$ROLE_MODEL" "$PROMPT_FULL" > "$LOG_FILE" 2>&1 || rc=$?
  fi
  return "$rc"
}

SESSION_ID=""
if [ "${RESET:-0}" -eq 0 ]; then
  SESSION_ID="$(read_session)"
fi

if [ "$BACKEND" = "cursor" ]; then
  # --- cursor backend: cursor-agent/agent headless with warm chats --------
  CURSOR_BIN="$(resolve_cursor_binary)" || {
    echo "error: cursor-agent (or agent) not found in PATH - install the Cursor CLI (https://cursor.com/docs/cli)" >&2
    exit 2
  }
  if [ -z "$ROLE_MODEL" ]; then
    echo "error: model for role '$ROLE' is not set ($ROLE_MODEL_VAR); run through run-pipeline.py or export it" >&2
    exit 2
  fi
  ROLE_BODY_FILE="$(role_body_file)" || {
    echo "error: role body file not found for role '$ROLE' (rerun install.py)" >&2
    exit 2
  }

  FIRST=0
  if [ -z "$SESSION_ID" ]; then
    FIRST=1
    # Mint a fresh chat through `create-chat`: its id always comes from
    # Cursor. A synthesized id in --resume is silently accepted by cursor
    # and starts an EMPTY chat, losing the context - so never invent one.
    # If create-chat fails, fall back to a bare run: cursor mints the chat
    # itself and the id is recovered from the JSON output below.
    CHAT_ID="$( "$CURSOR_BIN" create-chat 2>/dev/null | extract_chat_id )" || CHAT_ID=""
    if [ -n "$CHAT_ID" ]; then
      SESSION_ID="$CHAT_ID"
      save_session "$SESSION_ID"
    fi
  fi

  PROMPT_FULL="$PROMPT"
  if [ "$FIRST" -eq 1 ]; then
    # The chat is fresh and the LLM does not know its role yet: prefix the
    # role body once. Resumed chats stay hot and get the bare prompt.
    BODY="$(cat "$ROLE_BODY_FILE" 2>/dev/null || true)"
    PROMPT_FULL="$BODY

$PROMPT"
  fi

  RC=0
  cursor_run || RC=$?
  if [ "$RC" -ne 0 ]; then
    echo "run-agent: $CURSOR_BIN exited $RC; full log: $LOG_FILE" >&2
    exit "$RC"
  fi
  if [ -z "$SESSION_ID" ]; then
    # Fallback: the id was not obtained from create-chat, so recover it from
    # the JSON output (always a Cursor-minted id, never synthesized).
    SESSION_ID="$(extract_session_id)"
    if [ -n "$SESSION_ID" ]; then
      save_session "$SESSION_ID"
    fi
  fi
else
  # --- opencode backend ----------------------------------------------------
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
    opencode run --session "$SESSION_ID" --agent "$ROLE" --auto $ATTACH_FLAG --format json "$PROMPT" > "$LOG_FILE" 2>&1 || RC=$?
    if [ "$RC" -ne 0 ]; then
      echo "run-agent: opencode exited $RC; full log: $LOG_FILE" >&2
      exit "$RC"
    fi
  fi
fi

echo "SESSION:$SESSION_ID"
