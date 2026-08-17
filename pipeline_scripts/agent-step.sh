#!/usr/bin/env bash
# agent-step.sh - run one planner/executor prompt step of a workflow.
#
# The workflows never embed shell logic (CONTRIBUTING.md): this script is the
# single agent-step entry point the yaml calls. It exports STATE_DIR and the
# optional --export pairs (the prompt files substitute @TOKEN@ placeholders
# from the environment), resolves the prompts directory and delegates to
# run-agent.sh --prompt-file, which keeps the warm session and the logs.
#
# Usage: agent-step.sh <state_dir> <role> <prompt-file> [--export KEY=VALUE ...]
set -euo pipefail

usage() {
  echo "usage: $0 <state_dir> <role> <prompt-file> [--export KEY=VALUE ...]" >&2
  exit 2
}

[ $# -ge 3 ] || usage
STATE_DIR="$1"
ROLE="$2"
PROMPT_FILE="$3"
shift 3

export STATE_DIR
while [ $# -gt 0 ]; do
  case "$1" in
    --export)
      [ $# -ge 2 ] || usage
      export "$2"
      shift 2 ;;
    *) usage ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPTS_DIR="${SKLC_PROMPTS_DIR:-$HOME/.config/spec-kit-llm-client/prompts}"

exec "$SCRIPT_DIR/run-agent.sh" "$ROLE" --prompt-file "$PROMPTS_DIR/$PROMPT_FILE"
