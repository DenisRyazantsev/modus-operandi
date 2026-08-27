#!/usr/bin/env bash
# show-file.sh - print a file's contents to stdout, stripped of control
# characters (except \t and \n) - protection against ANSI injection from
# model-written text (ADR-0011).
#
# Usage: show-file.sh <state_dir> <file> [--block <label>]
#   <state_dir>  the workflow state directory (first argument, like the
#                other step scripts)
#   <file>       path relative to <state_dir> (slash-separated, no "../"
#                component - paths escaping state_dir are rejected)
#   --block <label>  wrap the output in the document-block markers
#                    (ADR-0021): MO-BLOCK-START:<label> before the content
#                    and MO-BLOCK-END after it; the wrapper then prints
#                    the content as a free-form block from the left
#                    margin. Errors still go to stderr (exit 1/2).
#
# Exit codes: 0 on success; 2 for a path escaping state_dir; 1 on a read
# error (message on stderr, stdout empty).
set -euo pipefail

usage() {
  echo "usage: $0 <state_dir> <file> [--block <label>]" >&2
  exit 2
}

[ $# -ge 2 ] || usage
STATE_DIR="$1"
FILE="$2"
shift 2

LABEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --block)
      [ $# -ge 2 ] || usage
      LABEL="$2"
      shift 2 ;;
    *) usage ;;
  esac
done

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
# sequences into the terminal (ADR-0011). The document-block markers
# (ADR-0021) wrap the stripped content; the wrapper consumes them. The
# file check above runs BEFORE the begin marker is emitted, so a missing
# file produces no markers on stdout.
if [ -n "$LABEL" ]; then
  echo "MO-BLOCK-START:$LABEL"
  # `awk '1'` re-prints the stripped content and appends the trailing
  # newline a file may lack, so MO-BLOCK-END always starts a fresh line:
  # the wrapper matches whole lines, and a glued marker would silently
  # degrade the block back to per-line rows.
  tr -d '\000-\010\013-\037\177' < "$STATE_DIR/$FILE" | awk '1'
  echo "MO-BLOCK-END"
else
  tr -d '\000-\010\013-\037\177' < "$STATE_DIR/$FILE"
fi
