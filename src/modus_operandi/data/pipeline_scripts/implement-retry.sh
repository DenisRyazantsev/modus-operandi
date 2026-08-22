#!/usr/bin/env bash
# implement-retry.sh - adr-pipeline implement-retry step (implement-loop).
#
# The first loop iteration asks the executor to redo the work; the marker
# keeps the loop from asking a second time (a second empty verify must fail
# the run, not repeat the prompt). The workflow never embeds shell logic
# (CONTRIBUTING.md), so the marker handling lives here.
#
# Usage: implement-retry.sh <state_dir>
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <state_dir>" >&2; exit 2; }
STATE_DIR="$1"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPTS_DIR="${MO_PROMPTS_DIR:-$HOME/.config/modus-operandi/prompts}"

if [ -f "$STATE_DIR/tasks/current/.implement-retried" ]; then
  echo "already retried once; the run will fail"
  exit 0
fi
touch "$STATE_DIR/tasks/current/.implement-retried"

export STATE_DIR
exec "$SCRIPT_DIR/run-agent.sh" executor --prompt-file "$PROMPTS_DIR/adr/implement-retry.md"
