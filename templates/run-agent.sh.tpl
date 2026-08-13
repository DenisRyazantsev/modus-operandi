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

while [ $$# -gt 0 ]; do
  case "$$1" in
    --task) shift 2 ;;
    --reset) RESET=1; shift ;;
    *) usage ;;
  esac
done

STATE_DIR="$${SKLC_STATE_DIR:-.workflow}"
SESSIONS_FILE="$$STATE_DIR/sessions.json"
ATTACH_FLAG="${serve_attach}"

mkdir -p "$$STATE_DIR"
if ! touch "$$SESSIONS_FILE"; then
  echo "error: cannot write $$SESSIONS_FILE" >&2
  exit 2
fi

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
  sed -n 's/.*"sessionID":"\([^"]*\)".*/\1/p' | head -1
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
    SESSION_ID="$$(printf '%s\n' "$$OUTPUT" | sed -n 's/.*"sessionId":"\([^"]*\)".*/\1/p' | head -1)"
  fi
  if [ -z "$$SESSION_ID" ]; then
    echo "error: could not extract a session id from opencode output" >&2
    exit 2
  fi
  save_session "$$SESSION_ID"
else
  opencode run --session "$$SESSION_ID" --agent "$$ROLE" --auto $$ATTACH_FLAG --format json "$$PROMPT"
fi

echo "SESSION:$$SESSION_ID"
