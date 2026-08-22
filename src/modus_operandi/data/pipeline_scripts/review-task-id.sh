#!/usr/bin/env bash
# review-task-id.sh - review-pipeline generate-task-id step.
#
# Builds a human-readable task id from the current git branch (fallback
# "review") plus a timestamp, creates the task dir and points
# <state_dir>/tasks/current at it. The workflow never embeds shell logic
# (CONTRIBUTING.md), so the id derivation lives here.
#
# Usage: review-task-id.sh <state_dir>
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <state_dir>" >&2; exit 2; }
STATE_DIR="$1"

mkdir -p "$STATE_DIR/tasks"
branch=$(git branch --show-current 2>/dev/null || true)
slug=$(printf '%s' "${branch:-review}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-40)
[ -n "$slug" ] || slug=review
tid="$slug-$(date +%Y%m%d-%H%M)"
mkdir -p "$STATE_DIR/tasks/$tid"
ln -sfn "$tid" "$STATE_DIR/tasks/current"
echo "task id: $tid"
