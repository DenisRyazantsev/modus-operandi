#!/usr/bin/env bash
# review-check.sh - one parallel review check of the review-fix-loop fan-out.
#
# The workflows never embed shell logic (CONTRIBUTING.md): the review fan-out
# calls this script once per pending kind. It dispatches the kind to its
# report prefix and prompt files, computes the next report number, exports
# STATE_DIR/LATEST/N(/SNAP) for the @TOKEN@ prompt substitution and runs the
# check in the per-kind fork of the warm planner session (ADR-0013: the first
# check of a kind forks the warm session, every later check continues the
# same fork).
#
# Usage: review-check.sh <state_dir> <task_id> <item> <prompt-ns>
#
#   item       one of srp|bugs|review|comment
#   prompt-ns  "review" (review-pipeline: rereview-vs-review selected by the
#              per-kind snapshot file) or "adr" (adr-pipeline: full review
#              every iteration, no snapshot)
set -euo pipefail

usage() {
  echo "usage: $0 <state_dir> <task_id> <item> <prompt-ns>" >&2
  exit 2
}

[ $# -eq 4 ] || usage
STATE_DIR="$1"
TASK_ID="$2"
ITEM="$3"
PROMPT_NS="$4"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPTS_DIR="${MO_PROMPTS_DIR:-$HOME/.config/modus-operandi/prompts}"

case "$ITEM" in
  srp) PREFIX=srp-review; PROMPT="$PROMPT_NS/srp-review.md"; REREVIEW="$PROMPT_NS/srp-rereview.md";;
  bugs) PREFIX=bug-review; PROMPT="$PROMPT_NS/bug-review.md"; REREVIEW="$PROMPT_NS/bug-rereview.md";;
  review) PREFIX=review; PROMPT="$PROMPT_NS/review.md"; REREVIEW="$PROMPT_NS/review-rereview.md";;
  comment) PREFIX=comment-review; PROMPT="$PROMPT_NS/comment-review.md"; REREVIEW="$PROMPT_NS/comment-rereview.md";;
  *) echo "error: unknown review kind '$ITEM'" >&2; exit 2;;
esac

latest=$(python3 "$SCRIPT_DIR/check_review.py" check-review "$STATE_DIR" "$TASK_ID" "$ITEM" 2>/dev/null || true)
n=1
if [ -n "$latest" ]; then
  b=$(basename "$latest")
  num=${b#$PREFIX-}
  num=${num%.md}
  case "$num" in ''|*[!0-9]*) num=0;; esac
  n=$((num+1))
fi

export STATE_DIR
export LATEST="$latest"
export N="$n"

# The adr pipeline reviews the full code on every iteration; only the
# review pipeline re-reviews a fix diff selected by a snapshot file.
if [ "$PROMPT_NS" = "review" ]; then
  snapfile="$STATE_DIR/tasks/current/$ITEM-snapshot.sha"
  if [ -s "$snapfile" ]; then
    export SNAP="$(cat "$snapfile")"
    "$SCRIPT_DIR/run-agent.sh" planner --review-fork "$ITEM" --prompt-file "$PROMPTS_DIR/$REREVIEW"
  else
    "$SCRIPT_DIR/run-agent.sh" planner --review-fork "$ITEM" --prompt-file "$PROMPTS_DIR/$PROMPT"
  fi
  # Snapshot the repository after the check: the next iteration's re-review
  # diffs the fixed code against it (untracked files are excluded - the
  # rereview prompts also ask for git status to cover them).
  snap=$(git stash create 2>/dev/null || true)
  [ -n "$snap" ] || snap=HEAD
  printf '%s' "$snap" > "$snapfile"
else
  "$SCRIPT_DIR/run-agent.sh" planner --review-fork "$ITEM" --prompt-file "$PROMPTS_DIR/$PROMPT"
fi
