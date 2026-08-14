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

if [ -n "$$TASK_ID" ] && ! printf '%s' "$$TASK_ID" | grep -qE '^[A-Za-z0-9_-]+$$'; then
  echo "error: invalid --task value '$$TASK_ID'; use only letters, digits, '_' or '-'" >&2
  exit 2
fi

STATE_DIR="$${SKLC_STATE_DIR:-.workflow}"
ATTACH_FLAG="${serve_attach}"
if [ -n "$$TASK_ID" ]; then
  SESSIONS_FILE="$$STATE_DIR/sessions-$$TASK_ID.json"
else
  SESSIONS_FILE="$$STATE_DIR/sessions.json"
fi
PID_FILE="$$STATE_DIR/pids/$$(basename "$$SESSIONS_FILE").pid"

mkdir -p "$$STATE_DIR/pids"
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
  OUTPUT="$$(opencode run --agent "$$ROLE" --auto $$ATTACH_FLAG --format json "$$PROMPT" 2>&1)" || RC=$$?
  printf '%s\n' "$$OUTPUT"
  if [ "$$RC" -ne 0 ]; then
    exit "$$RC"
  fi
  SESSION_ID="$$(printf '%s\n' "$$OUTPUT" | extract_session_id)"
  if [ -z "$$SESSION_ID" ]; then
    echo "error: could not extract a session id from opencode output" >&2
    exit 2
  fi
  save_session "$$SESSION_ID"
else
  opencode run --session "$$SESSION_ID" --agent "$$ROLE" --auto $$ATTACH_FLAG --format json "$$PROMPT"
fi

echo "SESSION:$$SESSION_ID"
