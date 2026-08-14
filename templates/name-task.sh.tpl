#!/usr/bin/env bash
# name-task.sh - one-shot task-slug generator for the adr-pipeline workflow.
#
# Usage: name-task.sh "<feature>"
#
# Asks the executor to derive a short kebab-case slug from a feature
# description and prints it. Used by the generate-task-id step to build a
# human-readable task id like mcc-split-20260814. One-shot: no session, no pid
# files (unlike run-agent.sh, which keeps warm opencode sessions per role).
#
# Environment:
#   (none)
set -euo pipefail

usage() {
  echo "usage: $$0 \"<feature>\"" >&2
  exit 2
}

[ $$# -ge 1 ] || usage
PROMPT="$$1"

ATTACH_FLAG="${serve_attach}"

# The executor is cheap and this is a trivial naming task; the slug feeds the
# task-id so it must be short and safe.
OUTPUT="$$(opencode run --agent executor --auto $$ATTACH_FLAG --format json "Reply with ONLY a short kebab-case slug (2-5 lowercase english words joined by hyphens, no quotes, no markdown, no explanation) describing this feature: $$PROMPT" 2>&1)" || RC=$$?
if [ "$${RC:-0}" -ne 0 ]; then
  printf '%s\n' "$$OUTPUT" >&2
  exit "$$RC"
fi
printf '%s\n' "$$OUTPUT" | python3 -c 'import json,sys
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
