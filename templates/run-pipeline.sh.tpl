#!/usr/bin/env bash
# run-pipeline.sh - run an installed workflow and surface the failing step's
# output in the terminal. specify hides shell-step stdout/stderr; on failure
# this wrapper re-reads the run's state file and prints it.
#
# Usage: run-pipeline.sh <workflow-id-or-path> [extra specify args...]
#   run-pipeline.sh review-pipeline
#   run-pipeline.sh adr-pipeline -i feature="..."
set -euo pipefail

SRC="$${1:?usage: run-pipeline.sh <workflow-id-or-path> [extra specify args...]}"
shift

RC=0
OUTPUT="$$(specify workflow run "$$SRC" "$$@" 2>&1)" || RC=$$?
printf '%s\n' "$$OUTPUT"
[ "$$RC" -eq 0 ] && exit 0

RUN_ID="$$(printf '%s\n' "$$OUTPUT" | python3 -c 'import json,sys,re
data = sys.stdin.read()
try:
    print(json.loads(data).get("run_id", ""))
except Exception:
    m = re.search(r"Run ID: ([0-9a-f]{8})", data)
    print(m.group(1) if m else "")')"
STATE="$${PWD}/.specify/workflows/runs/$${RUN_ID}/state.json"
if [ -n "$$RUN_ID" ] && [ -f "$$STATE" ]; then
  echo
  echo "failing step output:"
  python3 - "$$STATE" <<'PYEOF'
import json, sys

with open(sys.argv[1]) as fh:
    data = json.load(fh)
for sid, result in data.get("step_results", {}).items():
    out = result.get("output") or {}
    if result.get("status") != "completed" or out.get("stderr"):
        print(f"--- {sid} ({result.get('status')})")
        if out.get("stdout"):
            print(out["stdout"].rstrip())
        if out.get("stderr"):
            print(out["stderr"].rstrip())
PYEOF
fi
if [ -n "$$RUN_ID" ]; then
  echo
  echo "resume with: specify workflow resume $${RUN_ID}"
fi
exit "$$RC"
