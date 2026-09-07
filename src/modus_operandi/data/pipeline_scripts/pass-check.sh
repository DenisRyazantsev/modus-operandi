#!/usr/bin/env bash
# pass-check.sh - final review verdict report of both workflows.
#
# Lists the kinds whose latest report is not PASS (a WARNING never fails the
# run). The workflow never embeds shell logic (CONTRIBUTING.md), so the loop
# over the five kinds lives here.
#
# Usage: pass-check.sh <state_dir> <task_id>
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <state_dir> <task_id>" >&2; exit 2; }
STATE_DIR="$1"
TASK_ID="$2"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

fails=""
for kind in srp bugs review comment tests; do
  if ! python3 "$SCRIPT_DIR/check_review.py" check-review "$STATE_DIR" "$TASK_ID" "$kind" >/dev/null 2>&1; then
    fails="$fails $kind"
  fi
done
if [ -z "$fails" ]; then
  echo "REVIEW OK: all verdicts PASS"
else
  echo "WARNING: review loop exhausted all iterations without pass (kinds:$fails); inspect the latest review files and the code"
fi
