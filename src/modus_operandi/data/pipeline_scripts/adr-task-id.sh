#!/usr/bin/env bash
# adr-task-id.sh - task-pipeline generate-task-id step.
#
# Uses the explicit task id when given; otherwise asks the executor for a
# short English kebab-case slug (name-task.sh, one-shot) and appends a
# timestamp. Creates the task dir and points <state_dir>/tasks/current at it.
# The workflow never embeds shell logic (CONTRIBUTING.md), so the id
# derivation lives here. The task_id value was already validated by
# validate_inputs.py (validate-task-id step) before it reaches this script.
#
# Usage: adr-task-id.sh <state_dir> <task_id> <feature>
set -euo pipefail

[ $# -eq 3 ] || { echo "usage: $0 <state_dir> <task_id> <feature>" >&2; exit 2; }
STATE_DIR="$1"
TASK_ID="$2"
FEATURE="$3"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$STATE_DIR/tasks"
if [ -n "$TASK_ID" ]; then
  tid="$TASK_ID"
else
  slug=$("$SCRIPT_DIR/name-task.sh" "$FEATURE")
  slug=$(printf '%s' "$slug" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-40)
  [ -n "$slug" ] || slug=task
  tid="$slug-$(date +%Y%m%d-%H%M)"
fi
mkdir -p "$STATE_DIR/tasks/$tid"
ln -sfn "$tid" "$STATE_DIR/tasks/current"
echo "task id: $tid"
