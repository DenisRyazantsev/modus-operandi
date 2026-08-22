#!/usr/bin/env bash
# sync-adr.sh - adr-pipeline sync-adr step.
#
# When the executor recorded a deviation from the ADR, the planner amends
# adr.md with an "## Amendments" section, the amended ADR is written over the
# saved architecture/ADR-XXXX-<title>.md (save_adr.py sync) and the
# deviation file is removed. The workflow never embeds shell logic
# (CONTRIBUTING.md), so the deviation check lives here.
#
# Usage: sync-adr.sh <state_dir> <task_id>
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <state_dir> <task_id>" >&2; exit 2; }
STATE_DIR="$1"
TASK_ID="$2"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPTS_DIR="${MO_PROMPTS_DIR:-$HOME/.config/modus-operandi/prompts}"

if [ -f "$STATE_DIR/tasks/current/deviation.md" ]; then
  export STATE_DIR
  "$SCRIPT_DIR/run-agent.sh" planner --prompt-file "$PROMPTS_DIR/adr/sync-adr.md"
  python3 "$SCRIPT_DIR/save_adr.py" sync "$STATE_DIR" "$TASK_ID"
  rm -f "$STATE_DIR/tasks/current/deviation.md"
else
  echo "no deviation recorded"
fi
