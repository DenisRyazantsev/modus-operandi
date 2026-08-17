#!/usr/bin/env bash
# clear-feedback.sh - adr-pipeline adr-feedback-clear step.
#
# Removes the revise-gate feedback file after the planner applied it. The
# workflow never embeds shell logic (CONTRIBUTING.md), so even this single
# rm is a script call.
#
# Usage: clear-feedback.sh <state_dir>
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <state_dir>" >&2; exit 2; }
rm -f "$1/tasks/current/feedback.md"
