#!/usr/bin/env bash
# implement-pass-check.sh - task-pipeline implement-pass-check step.
#
# Fails the run when two implement attempts produced no repository changes.
# The workflow never embeds shell logic (CONTRIBUTING.md), so the check and
# the error message live here.
#
# Usage: implement-pass-check.sh <state_dir> <adr_dir> <run_id>
set -euo pipefail

[ $# -eq 3 ] || { echo "usage: $0 <state_dir> <adr_dir> <run_id>" >&2; exit 2; }
STATE_DIR="$1"
ADR_DIR="$2"
RUN_ID="$3"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if python3 "$SCRIPT_DIR/check_implementation.py" check "$ADR_DIR"; then
  echo "IMPLEMENT OK: changes present"
else
  echo "error: the executor made no changes to the repository in two attempts (task state: $STATE_DIR/tasks/current; agent log: $STATE_DIR/logs); resume with: specify workflow resume $RUN_ID" >&2
  exit 1
fi
