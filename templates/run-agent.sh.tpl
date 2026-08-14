#!/usr/bin/env bash
# run-agent.sh - session glue for the adr-pipeline workflow.
#
# Usage: run-agent.sh <role> "<prompt>" [--task <task-id>] [--reset]
#
# Keeps one warm opencode session per role (stored in <state_dir>/sessions.json)
# and resumes it with `opencode run --session` between workflow steps, so the
# agent does not re-read the project on every step.
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
#   SKLC_STATE_DIR  state directory (default: .workflow relative to cwd)
set -euo pipefail

usage() {
  echo "usage: $$0 <role> \"<prompt>\" [--task <task-id>] [--reset]" >&2
  echo "       role must be 'planner' or 'executor'" >&2
  exit 2
}

[ $$# -ge 2 ] || usage
ROLE="$$1"
PROMPT="$$2"
shift 2
[ "$$ROLE" = "planner" ] || [ "$$ROLE" = "executor" ] || usage

TASK_ID=""
RESET=0
while [ $$# -gt 0 ]; do
  case "$$1" in
    --task) [ $$# -ge 2 ] || usage; TASK_ID="$$2"; shift 2 ;;
    --reset) RESET=1; shift ;;
    *) usage ;;
  esac
done

STATE_DIR="$${SKLC_STATE_DIR:-.workflow}"
ATTACH_FLAG="${serve_attach}"

if [ -z "$$TASK_ID" ]; then
  # The workflow generates the task id at runtime; recover it from the
  # tasks/current symlink instead of templating the id into every prompt.
  if [ -e "$$STATE_DIR/tasks/current" ]; then
    TARGET="$$(readlink -f "$$STATE_DIR/tasks/current" 2>/dev/null || true)"
    [ -n "$$TARGET" ] && TASK_ID="$$(basename "$$TARGET")"
  fi
fi

if [ -n "$$TASK_ID" ] && ! printf '%s' "$$TASK_ID" | grep -qE '^[A-Za-z0-9_-]+$$'; then
  echo "error: invalid --task value '$$TASK_ID'; use only letters, digits, '_' or '-'" >&2
  exit 2
fi
if [ -n "$$TASK_ID" ]; then
  SESSIONS_FILE="$$STATE_DIR/sessions-$$TASK_ID.json"
else
  SESSIONS_FILE="$$STATE_DIR/sessions.json"
fi
PID_FILE="$$STATE_DIR/pids/$$(basename "$$SESSIONS_FILE").$$ROLE.pid"
LOG_DIR="$$STATE_DIR/logs"
LOG_FILE="$$LOG_DIR/$$(basename "$$SESSIONS_FILE" .json)-$$ROLE.jsonl"

mkdir -p "$$STATE_DIR/pids" "$$LOG_DIR"
if ! touch "$$SESSIONS_FILE"; then
  echo "error: cannot write $$SESSIONS_FILE" >&2
  exit 2
fi

# Kill any opencode process left over from a previously killed step (e.g. a
# shell-step timeout that killed the shell but not the agent), so a zombie
# cannot keep writing to this session or burn tokens.
if [ -f "$$PID_FILE" ]; then
  OLD_PID="$$(cat "$$PID_FILE" 2>/dev/null || true)"
  if [ -n "$$OLD_PID" ] && kill -0 "$$OLD_PID" 2>/dev/null; then
    if ps -p "$$OLD_PID" -o comm= 2>/dev/null | grep -q '^opencode'; then
      echo "warning: killing stale opencode process $$OLD_PID for role '$$ROLE'" >&2
      kill "$$OLD_PID" 2>/dev/null || true
    fi
  fi
  rm -f "$$PID_FILE"
fi
echo "$$$$" > "$$PID_FILE"
trap 'rm -f "$$PID_FILE"' EXIT

read_session() {
  python3 -c 'import json,sys
p, r = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(p))
    sys.stdout.write(d.get(r, ""))
except Exception:
    pass' "$$SESSIONS_FILE" "$$ROLE"
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
    json.dump(d, f, indent=2)' "$$SESSIONS_FILE" "$$ROLE" "$$1"
}

extract_session_id() {
  sed -n 's/.*"session[iI][dD]":"\([^"]*\)".*/\1/p' | head -1
}

SESSION_ID=""
if [ "$${RESET:-0}" -eq 0 ]; then
  SESSION_ID="$$(read_session)"
fi

if [ -z "$$SESSION_ID" ]; then
  RC=0
  # Stream opencode into a log file instead of a command substitution: the
  # JSON event stream is large, and capturing it through a pipe made opencode
  # die with SIGPIPE (exit 141) mid-run. A file also keeps a durable per-role
  # log the user can inspect after a failed step.
  opencode run --agent "$$ROLE" --auto $$ATTACH_FLAG --format json "$$PROMPT" > "$$LOG_FILE" 2>&1 || RC=$$?
  cat "$$LOG_FILE"
  if [ "$$RC" -ne 0 ]; then
    echo "run-agent: opencode exited $$RC; full log: $$LOG_FILE" >&2
    exit "$$RC"
  fi
  SESSION_ID="$$(extract_session_id < "$$LOG_FILE")"
  if [ -z "$$SESSION_ID" ]; then
    echo "error: could not extract a session id from opencode output" >&2
    exit 2
  fi
  save_session "$$SESSION_ID"
else
  RC=0
  opencode run --session "$$SESSION_ID" --agent "$$ROLE" --auto $$ATTACH_FLAG --format json "$$PROMPT" > "$$LOG_FILE" 2>&1 || RC=$$?
  cat "$$LOG_FILE"
  if [ "$$RC" -ne 0 ]; then
    echo "run-agent: opencode exited $$RC; full log: $$LOG_FILE" >&2
    exit "$$RC"
  fi
fi

echo "SESSION:$$SESSION_ID"
