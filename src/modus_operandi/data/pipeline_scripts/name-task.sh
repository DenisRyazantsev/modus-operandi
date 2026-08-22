#!/usr/bin/env bash
# name-task.sh - one-shot task-slug generator for the task-pipeline workflow.
#
# Usage: name-task.sh "<feature>"
#
# Asks the executor to derive a short kebab-case slug from a feature
# description and prints it. Used by the generate-task-id step to build a
# human-readable task id like mcc-split-20260814. One-shot: no session, no pid
# files (unlike run-agent.sh, which keeps warm sessions per role).
#
# The backend is selected by MO_BACKEND (exported by the run-pipeline.py
# wrapper; default opencode):
#   opencode -> `opencode run --agent executor ...` + JSON-stream parse
#   cursor   -> `cursor-agent -p --output-format text --model <executor-model>`
#               (text output contains only the final answer, no parsing)
#
# Environment:
#   MO_ATTACH_FLAG   extra opencode flag, e.g. --attach http://localhost:4096
#                      (set by the run-pipeline.py wrapper from use_serve)
#   MO_BACKEND       active backend: opencode (default) or cursor
#   MO_EXECUTOR_MODEL
#                      executor model of the active backend (used only by cursor)
set -euo pipefail

usage() {
  echo "usage: $0 \"<feature>\"" >&2
  exit 2
}

[ $# -ge 1 ] || usage
PROMPT="$1"

ATTACH_FLAG="${MO_ATTACH_FLAG:-}"
BACKEND="${MO_BACKEND:-opencode}"

if [ "$BACKEND" = "cursor" ]; then
  CURSOR_BIN=""
  if command -v cursor-agent >/dev/null 2>&1; then
    CURSOR_BIN="cursor-agent"
  elif command -v agent >/dev/null 2>&1; then
    CURSOR_BIN="agent"
  fi
  if [ -z "$CURSOR_BIN" ]; then
    echo "error: cursor-agent (or agent) not found in PATH - install the Cursor CLI (https://cursor.com/docs/cli)" >&2
    exit 2
  fi
  ROLE_MODEL="${MO_EXECUTOR_MODEL:-}"
  if [ -z "$ROLE_MODEL" ]; then
    echo "error: executor model is not set (MO_EXECUTOR_MODEL); run through run-pipeline.py or export it" >&2
    exit 2
  fi
  # The executor is cheap and this is a trivial naming task; the slug feeds
  # the task-id so it must be short and safe. Text output is the final answer
  # only, so no JSON-stream parsing is needed - just trim the outer
  # whitespace (the workflow sanitizes the slug further).
  OUTPUT="$("$CURSOR_BIN" -p --output-format text --force --trust --model "$ROLE_MODEL" "Reply with ONLY a short kebab-case slug (2-5 lowercase english words joined by hyphens, no quotes, no markdown, no explanation) describing this feature: $PROMPT" 2>&1)" || RC=$?
  if [ "${RC:-0}" -ne 0 ]; then
    printf '%s\n' "$OUTPUT" >&2
    exit "$RC"
  fi
  printf '%s\n' "$OUTPUT" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
  exit 0
fi

# The executor is cheap and this is a trivial naming task; the slug feeds the
# task-id so it must be short and safe.
OUTPUT="$(opencode run --agent executor --auto $ATTACH_FLAG --format json "Reply with ONLY a short kebab-case slug (2-5 lowercase english words joined by hyphens, no quotes, no markdown, no explanation) describing this feature: $PROMPT" 2>&1)" || RC=$?
if [ "${RC:-0}" -ne 0 ]; then
  printf '%s\n' "$OUTPUT" >&2
  exit "$RC"
fi
printf '%s\n' "$OUTPUT" | python3 -c 'import json,sys
texts = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    p = d.get("part", {})
    # opencode streams many text parts per run (thinking, tool calls, ...);
    # the final one is the reply, so take texts[-1]. The event-level "text"
    # check filters out non-message events; the part-level one selects
    # actual payload parts.
    if d.get("type") == "text" and p.get("type") == "text" and p.get("text"):
        texts.append(p["text"])
sys.stdout.write(texts[-1] if texts else "")'
exit 0
