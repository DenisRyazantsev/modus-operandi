# run-agent-cursor.sh - the cursor backend of run-agent.sh (sourced by it).
#
# One responsibility: the cursor-agent/agent backend — resolve the binary,
# mint/resume warm chats, prefix the role body on a fresh chat and run the
# headless invocation. Sourced into run-agent.sh's shell when
# SKLC_BACKEND=cursor: it reads the role/prompt/model/session variables and
# writes back SESSION_ID, so run-agent.sh's final "SESSION:<id>" line works
# for both backends. A change to the cursor backend touches only this file.
#
# Warm chats are per-role and per review kind: the per-kind review chats
# (ADR-0013) are minted with `create-chat` on the kind's first check and
# resumed with `--resume <chatId>` on every later check, so the reviewer
# keeps its past findings across the review-fix-loop iterations. The minted
# id is saved to the per-kind session file (SESSIONS_FILE already points at
# it), never to the per-role store — the warm parent chat id stays
# authoritative and is never resumed or mutated. cursor-agent has no fork
# primitive (`opencode run --session <id> --fork` is opencode-only), so the
# per-kind chat IS the fork: a fresh chat that inherits the review context
# only through the review prompts themselves.

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

run_cursor_once() {
  # One headless cursor-agent invocation for the current turn; `--resume` is
  # added only when a saved chat id exists. Nothing is echoed from the JSON
  # stream to the step's stdout: the workflow runner captures step output
  # through a pipe, and a large stream made the reader close early,
  # SIGPIPE-ing this script (exit 141).
  #
  # The cursor CLI prints non-JSON status lines (e.g. "Connection lost,
  # reconnecting...") on the same stream even with --output-format json, so
  # the invocation writes into a raw sidecar first and only the valid JSON
  # lines are copied into $LOG_FILE below — the .jsonl stays pure for
  # extract_session_id and the log tailer, while the full raw output stays
  # inspectable in the sidecar (the raw file is per-invocation and may be
  # truncated).
  #
  # The valid JSON lines are APPENDED to $LOG_FILE, never written over it:
  # the per-kind review logs are stable files reused by every
  # review-fix-loop iteration (ADR-0013), so truncating on each call would
  # erase the previous iterations' events and the end-of-run statistics
  # (collect_cursor_usage sums every .jsonl of the task) would undercount
  # all but the last iteration. Appending also keeps the live-line tailer's
  # byte offsets monotonic, so events are never re-read into the
  # accumulators.
  #
  # The agent runs in the BACKGROUND so its pid can be recorded (the stale-
  # process cleanup in manage_pid_file matches the recorded pid's name).
  local rc=0
  local raw="${LOG_FILE%.jsonl}.raw"
  if [ -n "$SESSION_ID" ]; then
    "$CURSOR_BIN" -p --output-format json --force --trust --workspace "$(pwd)" --model "$ROLE_MODEL" --resume "$SESSION_ID" "$PROMPT_FULL" > "$raw" 2>&1 &
  else
    "$CURSOR_BIN" -p --output-format json --force --trust --workspace "$(pwd)" --model "$ROLE_MODEL" "$PROMPT_FULL" > "$raw" 2>&1 &
  fi
  AGENT_PID=$!
  record_agent_pid "$AGENT_PID"
  wait "$AGENT_PID" || rc=$?
  python3 - "$raw" "$LOG_FILE" <<'PYEOF'
import json
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8", errors="replace") as fh, open(
    dst, "a", encoding="utf-8"
) as out:
    for line in fh:
        if not line.strip():
            continue
        try:
            json.loads(line)
        except Exception:
            continue
        out.write(line)
PYEOF
  return "$rc"
}

run_cursor() {
  # The cursor branch body: resolve the binary, require the role model, mint
  # or resume a warm chat and prefix the role body on a fresh one. Sets
  # SESSION_ID for run-agent.sh's final "SESSION:<id>" line.
  local CURSOR_BIN ROLE_BODY_FILE FIRST CHAT_ID PROMPT_FULL BODY RC
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
    # SESSION_ID is guaranteed empty here on a kind's FIRST check: with
    # --review-fork, session_paths pointed SESSIONS_FILE at the per-kind
    # file, so run-agent.sh's read_session never loads the warm parent id
    # into SESSION_ID. The old ADR-0009 guard "a fork must never fall back
    # to the stored warm chat" therefore became UNREACHABLE when the
    # --fork flag was removed (ADR-0013), not lost: a failed create-chat
    # below can never resume the warm parent chat.
    # Mint a fresh chat through `create-chat`: its id always comes from
    # Cursor. A synthesized id in --resume is silently accepted by cursor
    # and starts an EMPTY chat, losing the context - so never invent one.
    # If create-chat fails, fall back to a bare run: cursor mints the chat
    # itself and the id is recovered from the JSON output below.
    CHAT_ID="$( "$CURSOR_BIN" create-chat 2>/dev/null | extract_chat_id )" || CHAT_ID=""
    if [ -n "$CHAT_ID" ]; then
      SESSION_ID="$CHAT_ID"
      # The fresh chat id is saved to the CURRENT store file: the per-role
      # file for a warm chat, the per-kind file for a review chat (ADR-0013)
      # — the review chat never touches the per-role store, so the warm
      # parent id stays authoritative.
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
  run_cursor_once || RC=$?
  if [ "$RC" -ne 0 ]; then
    echo "run-agent: $CURSOR_BIN exited $RC; full log: $LOG_FILE (raw output: ${LOG_FILE%.jsonl}.raw)" >&2
    exit "$RC"
  fi
  if [ -z "$SESSION_ID" ]; then
    # Fallback: the id was not obtained from create-chat, so recover it from
    # the JSON output (always a Cursor-minted id, never synthesized). The id
    # is saved to the current store file (per-role or per-kind, ADR-0013).
    SESSION_ID="$(extract_session_id)"
    if [ -n "$SESSION_ID" ]; then
      save_session "$SESSION_ID"
    fi
  fi
}
