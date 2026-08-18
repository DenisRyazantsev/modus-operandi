#!/usr/bin/env bash
# show-file.sh - print a file's contents to stdout, stripped of control
# characters (except \t and \n) - protection against ANSI injection from
# model-written text (ADR-0011).
#
# Usage: show-file.sh <state_dir> <file>
#   <state_dir>  the workflow state directory (first argument, like the
#                other step scripts)
#   <file>       path relative to <state_dir> (slash-separated, no "../"
#                component - paths escaping state_dir are rejected)
#
# Exit codes: 0 on success; 2 for a path escaping state_dir; 1 on a read
# error (message on stderr, stdout empty).
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <state_dir> <file>" >&2; exit 2; }
STATE_DIR="$1"
FILE="$2"

# Any "../" component escapes the state dir (leading, mid-path or trailing):
# the file argument comes from the workflow, so the check is a guard, not a
# convenience.
case "/$FILE" in
  */../*|*/..)
    echo "error: path escapes state_dir: $FILE" >&2
    exit 2
    ;;
esac

if [ ! -f "$STATE_DIR/$FILE" ]; then
  echo "error: cannot read $STATE_DIR/$FILE" >&2
  exit 1
fi

# Strip the C0 control characters except \t (0x09) and \n (0x0A), plus DEL
# (0x7F): the text comes from the model and must not carry ANSI escape
# sequences into the terminal.
tr -d '\000-\010\013-\037\177' < "$STATE_DIR/$FILE"
