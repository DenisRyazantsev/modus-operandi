# session_store.sh - per-role session persistence for run-agent.sh (sourced).
#
# One responsibility: the per-role session id records (sessions-<task-id>.json),
# the pid files and the stale-agent cleanup, shared by both backends. Sourced
# into run-agent.sh's shell, so the functions read the caller's STATE_DIR /
# TASK_ID / ROLE / BACKEND variables and set SESSIONS_FILE / PID_FILE /
# LOG_FILE. A change to the session storage or to the stale-agent cleanup
# touches only this file.

session_paths() {
  # Per-role session record base name: sessions-<task-id>.json, or
  # sessions.json without a task id.
  if [ -n "$TASK_ID" ]; then
    BASE="sessions-$TASK_ID"
  else
    BASE="sessions"
  fi
  ROLE_SESSIONS_FILE="$STATE_DIR/$BASE.json"
  SESSIONS_FILE="$ROLE_SESSIONS_FILE"
  if [ -n "${REVIEW_FORK:-}" ]; then
    # A per-kind review session. One file per kind (srp|bugs|review|comment|tests):
    # the five parallel first-time checks never race on one file
    # (session_store reads/writes a JSON file whole).
    SESSIONS_FILE="$STATE_DIR/$BASE-review-$REVIEW_FORK.json"
  fi
  PID_FILE="$STATE_DIR/pids/$(basename "$SESSIONS_FILE" .json).$ROLE.pid"
  LOG_DIR="$STATE_DIR/logs"
  LOG_FILE="$LOG_DIR/$(basename "$SESSIONS_FILE" .json)-$ROLE.jsonl"
  if [ -n "${REVIEW_FORK:-}" ]; then
    # Stable per-kind log/pid names: the tailer labels the live line
    # [reviewer-srp] and the token sums continue between the
    # review-fix-loop iterations, because the same file is reused. The kind
    # is already part of the reviewer role name, so no -fork-<kind> suffix
    # is needed: the log file is named after the role only
    # (sessions-<task>-reviewer-srp.jsonl).
    PID_FILE="$STATE_DIR/pids/$BASE-$ROLE.pid"
    LOG_FILE="$LOG_DIR/$BASE-$ROLE.jsonl"
  fi
}

read_session() {
  read_session_from "$SESSIONS_FILE"
}

read_session_from() {
  # Read the session id for ROLE from a given store file. Used to read the
  # per-role store while SESSIONS_FILE points at a per-kind review file.
  python3 -c 'import json,sys
p, r = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(p))
    sys.stdout.write(d.get(r, ""))
except Exception:
    pass' "$1" "$ROLE"
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
  # and cursor's "session_id" JSON fields alike. The LAST match is taken:
  # cursor logs accumulate across calls (run-agent-cursor.sh appends), so
  # the newest event carries the id of the CURRENT call — the first match
  # would resurrect an older chat's id after a bare-run re-mint. Opencode
  # logs are truncated per call, where first and last match coincide.
  python3 -c 'import re, sys
ms = re.findall(rb"\"session[_]?[iI][dD]\":\"([^\"]*)\"", open(sys.argv[1], "rb").read())
if ms:
    sys.stdout.write(ms[-1].decode())' "$LOG_FILE"
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
  # is replaced). This applies to the per-role files and to the per-kind
  # reviewer files alike: both have stable names, so a later step CAN target
  # them for the stale-kill.
  echo "$1" > "$PID_FILE"
}
