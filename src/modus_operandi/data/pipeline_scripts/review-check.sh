#!/usr/bin/env bash
# review-check.sh - one parallel review check of the review-fix-loop fan-out.
#
# The workflows never embed shell logic (CONTRIBUTING.md): the review fan-out
# calls this script once per pending kind. It dispatches the kind to its
# report prefix and prompt files, computes the next report number, exports
# STATE_DIR/LATEST/N(/SNAP) for the @TOKEN@ prompt substitution and runs the
# check in the per-kind session of the dedicated reviewer role
# (reviewer-srp|reviewer-bugs|reviewer-review|reviewer-comment|reviewer-tests). The first
# check of a kind starts a fresh session that receives ONLY the plan and the
# ADR (via the step prompt) — it never inherits the planner's context; every
# later check continues the same session, so the reviewer keeps its past
# findings across the review-fix-loop iterations.
#
# Usage: review-check.sh <state_dir> <task_id> <item> <prompt-ns>
#
#   item       one of srp|bugs|review|comment|tests
#   prompt-ns  "review" (review-pipeline: rereview-vs-review selected by the
#              per-kind snapshot file) or "adr" (task-pipeline: full review
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
  srp) PREFIX=srp-review; PROMPT="$PROMPT_NS/srp-review.md"; REREVIEW="$PROMPT_NS/srp-rereview.md"; ROLE=reviewer-srp;;
  bugs) PREFIX=bug-review; PROMPT="$PROMPT_NS/bug-review.md"; REREVIEW="$PROMPT_NS/bug-rereview.md"; ROLE=reviewer-bugs;;
  review) PREFIX=review; PROMPT="$PROMPT_NS/review.md"; REREVIEW="$PROMPT_NS/review-rereview.md"; ROLE=reviewer-review;;
  comment) PREFIX=comment-review; PROMPT="$PROMPT_NS/comment-review.md"; REREVIEW="$PROMPT_NS/comment-rereview.md"; ROLE=reviewer-comment;;
  tests) PREFIX=tests-review; PROMPT="$PROMPT_NS/tests-review.md"; REREVIEW="$PROMPT_NS/tests-rereview.md"; ROLE=reviewer-tests;;
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
    "$SCRIPT_DIR/run-agent.sh" "$ROLE" --review-fork "$ITEM" --prompt-file "$PROMPTS_DIR/$REREVIEW"
  else
    "$SCRIPT_DIR/run-agent.sh" "$ROLE" --review-fork "$ITEM" --prompt-file "$PROMPTS_DIR/$PROMPT"
  fi
  # Snapshot the repository after the check: the next iteration's re-review
  # diffs the fixed code against it (untracked files are excluded - the
  # rereview prompts also ask for git status to cover them). An unborn HEAD
  # (a fresh repo, which determine-scope.sh explicitly supports) makes
  # `git stash create` fail and HEAD itself unresolvable, so the snapshot
  # stays empty there: the existing `[ -s "$snapfile" ]` check then treats
  # it as "no snapshot yet" and the next iteration runs the full review,
  # which is correct when there is no previous state to diff against.
  if git rev-parse --verify --quiet HEAD >/dev/null 2>&1; then
    snap=$(git stash create 2>/dev/null || true)
    [ -n "$snap" ] || snap=HEAD
  else
    snap=""
  fi
  printf '%s' "$snap" > "$snapfile"
else
  "$SCRIPT_DIR/run-agent.sh" "$ROLE" --review-fork "$ITEM" --prompt-file "$PROMPTS_DIR/$PROMPT"
fi
