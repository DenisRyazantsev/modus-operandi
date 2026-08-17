#!/usr/bin/env bash
# warm-planner.sh - review-pipeline warm-planner step.
#
# opencode: warm the planner session now, so the four parallel checks each
# run in a FORK of it and inherit the loaded review scope (ADR-0009).
#
# cursor: cursor-agent has no fork primitive - the checks mint fresh chats,
# so the warm-up itself is pointless. Instead this step PRE-FLIGHTS the
# cursor backend: the binary, the role models and the role bodies must be
# present, otherwise the same error would fail all four fan-out checks at
# once, deep inside the loop where specify hides the step stderr.
#
# Usage: warm-planner.sh <state_dir>
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <state_dir>" >&2; exit 2; }
STATE_DIR="$1"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPTS_DIR="${SKLC_PROMPTS_DIR:-$HOME/.config/spec-kit-llm-client/prompts}"
BACKEND="${SKLC_BACKEND:-opencode}"

if [ "$BACKEND" != "cursor" ]; then
  export STATE_DIR
  exec "$SCRIPT_DIR/run-agent.sh" planner --prompt-file "$PROMPTS_DIR/review/warmup.md"
fi

# --- cursor pre-flight -----------------------------------------------------
# The binary resolution mirrors run-agent-cursor.sh (cursor-agent preferred,
# `agent` only as a fallback because other tools ship an unrelated `agent`).
if ! command -v cursor-agent >/dev/null 2>&1 && ! command -v agent >/dev/null 2>&1; then
  echo "error: cursor backend: cursor-agent (or agent) not found in PATH - install the Cursor CLI (https://cursor.com/docs/cli)" >&2
  exit 2
fi
if [ -z "${SKLC_PLANNER_MODEL:-}" ] || [ -z "${SKLC_EXECUTOR_MODEL:-}" ]; then
  echo "error: cursor backend: planner/executor models are not set (SKLC_PLANNER_MODEL/SKLC_EXECUTOR_MODEL); run through run-pipeline.py or export them" >&2
  exit 2
fi
for role in planner executor; do
  body="$SCRIPT_DIR/$role-body.txt"
  if [ ! -f "$body" ]; then
    echo "error: cursor backend: role body file not found: $body (rerun install.py)" >&2
    exit 2
  fi
done

echo "cursor backend: skipping warm-up (parallel checks mint fresh chats)"
