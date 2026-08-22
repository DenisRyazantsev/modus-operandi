#!/usr/bin/env bash
# prompt_subst.sh - substitute @TOKEN@ placeholders in a prompt file.
#
# The workflow steps export STATE_DIR/LATEST/N/SNAP/etc. before the call, so
# the prompt files stay plain .md text with no shell or template escapes.
# The @[A-Z0-9_]+@ token format is the only thing this script changes, so a
# prompt-format change touches exactly one file.
#
# Usage: prompt_subst.sh <prompt-file>   (prints the substituted text)
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <prompt-file>" >&2; exit 2; }

python3 - "$1" <<'PYEOF'
import os
import re
import sys
text = open(sys.argv[1], encoding="utf-8").read()
sys.stdout.write(re.sub(r"@([A-Z0-9_]+)@", lambda m: os.environ.get(m.group(1), m.group(0)), text))
PYEOF
