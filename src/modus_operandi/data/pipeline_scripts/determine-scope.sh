#!/usr/bin/env bash
# determine-scope.sh - review-pipeline determine-scope step.
#
# Writes <state_dir>/scope.txt ("full" or "branch-diff: <base>") and, in
# branch-diff mode, <state_dir>/base-branch.txt. The workflow never embeds
# shell logic (CONTRIBUTING.md), so the whole scope detection lives here.
#
# `git diff --quiet` ignores untracked files, so a branch (or fresh repo)
# containing only NEW files would falsely report "no changes"; the
# untracked-file check counts them as changes too.
#
# Usage: determine-scope.sh <state_dir> <branch-diff>
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <state_dir> <branch-diff>" >&2; exit 2; }
STATE_DIR="$1"
BRANCH_DIFF="$2"

if [ "$BRANCH_DIFF" = "true" ]; then
  # Outside a git repo every probe below would fail and the review would run
  # against a meaningless "HEAD" scope — tell the user instead.
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "error: not a git repository - branch-diff review requires git" >&2
    exit 1
  fi
  base=""
  if git symbolic-ref -q refs/remotes/origin/HEAD >/dev/null 2>&1; then
    base=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/@@')
  fi
  if [ -z "$base" ]; then
    for b in origin/main origin/master main master; do
      if git rev-parse --verify --quiet "$b" >/dev/null 2>&1; then base="$b"; break; fi
    done
  fi
  if [ -z "$base" ]; then
    echo "WARNING: no main/master branch found; reviewing against HEAD"
    base="HEAD"
  fi
  if git rev-parse --verify --quiet HEAD >/dev/null 2>&1; then
    if git diff "$base" --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
      echo "error: no changes against $base - nothing to review" >&2
      exit 1
    fi
  elif [ -z "$(git ls-files --others --exclude-standard)" ]; then
    # Unborn HEAD (a fresh repo with no commits): `git diff HEAD` cannot
    # run, so only untracked files can be changes.
    echo "error: no changes against HEAD - nothing to review" >&2
    exit 1
  fi
  printf '%s' "$base" > "$STATE_DIR/base-branch.txt"
  printf 'branch-diff: %s' "$base" > "$STATE_DIR/scope.txt"
  echo "mode: branch-diff (base: $base)"
else
  rm -f "$STATE_DIR/base-branch.txt"
  printf 'full' > "$STATE_DIR/scope.txt"
  echo "mode: full codebase review"
fi
