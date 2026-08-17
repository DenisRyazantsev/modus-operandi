# session_store.sh - per-role session persistence for run-agent.sh (sourced).
#
# One responsibility: the per-role session id records (sessions-<task-id>.json),
# the pid files and the stale-agent cleanup, shared by both backends. Sourced
# into run-agent.sh's shell, so the functions read the caller's STATE_DIR /
# TASK_ID / ROLE / BACKEND variables and set SESSIONS_FILE / PID_FILE /
# LOG_FILE. A change to the session storage or to the stale-agent cleanup
# touches only this file.

session_paths() {
  if [ -n "$TASK_ID" ]; then
    SESSIONS_FILE="$STATE_DIR/sessions-$TASK_ID.json"
  else
    SESSIONS_FILE="$STATE_DIR/sessions.json"
  fi
  PID_FILE="$STATE_DIR/pids/$(basename "$SESSIONS_FILE").$ROLE.pid"
  LOG_DIR="$STATE_DIR/logs"
  LOG_FILE="$LOG_DIR/$(basename "$SESSIONS_FILE" .json)-$ROLE.jsonl"
}

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

manage_pid_file() {
  # Kill any agent process left over from a previously killed step (e.g. a
  # shell-step timeout that killed the shell but not the agent), so a zombie
  # cannot keep writing to this session or burn tokens. The pid file records
  # the AGENT process (record_agent_pid, called right after the agent is
  # spawned in the background), never the shell: the stale-check compares the
  # recorded pid's process name against the backend pattern below, and the
  # shell's own name would never match it. The process name to match depends
  # on the backend: opencode vs cursor-agent/agent.
  local backend="$1"
  local STALE_PROC_PATTERN
  if [ "$backend" = "cursor" ]; then
    STALE_PROC_PATTERN='^(cursor-agent|agent)$'
  else
    STALE_PROC_PATTERN='^opencode'
  fi
  mkdir -p "$STATE_DIR/pids" "$LOG_DIR"
  if ! touch "$SESSIONS_FILE"; then
    echo "error: cannot write $SESSIONS_FILE" >&2
    exit 2
  fi
  if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
      if ps -p "$OLD_PID" -o comm= 2>/dev/null | grep -qE "$STALE_PROC_PATTERN"; then
        echo "warning: killing stale $backend process $OLD_PID for role '$ROLE'" >&2
        kill "$OLD_PID" 2>/dev/null || true
      fi
    fi
    rm -f "$PID_FILE"
  fi
}

record_agent_pid() {
  # Write the spawned agent's pid into the pid file. The file must survive a
  # killed shell: no EXIT trap here, so when the workflow timeout kills the
  # step shell but not the agent, the next step's manage_pid_file finds the
  # orphan pid and kills it. A dead pid is harmless (kill -0 fails, the file
  # is replaced). Fork pid files carry a per-invocation -fork-<pid> name that
  # no later step can target, so they ARE removed on exit to keep the pids
  # dir clean.
  echo "$1" > "$PID_FILE"
  if [ "${FORK:-0}" -eq 1 ]; then
    trap 'rm -f "$PID_FILE"' EXIT
  fi
}
