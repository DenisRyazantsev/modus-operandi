#!/usr/bin/env python3
"""Install the spec-run planner/executor pipeline (dev flow).

Usage:
  python3 install.py [--uninstall] [--home DIR] [--yes]

Installs the global opencode agents (planner, executor), the pipeline
scripts and the task/review workflows from the package sources in src/ into
~/.config/spec-run/ and ~/.config/opencode/. See README.md for usage.

Options:
  --uninstall    remove the installed files (asks for confirmation)
  --home DIR     base directory instead of the real home (used by tests)
  --yes          answer yes to all prompts
"""

import sys
from pathlib import Path

# The package lives in src/ (src layout): make it importable from a plain
# checkout so `python3 install.py` works without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from spec_run.installer_cli import main

if __name__ == "__main__":
    sys.exit(main())
