#!/usr/bin/env python3
"""Install the spec-kit-llm-client planner/executor pipeline.

Usage:
  python3 install.py [--update] [--uninstall] [--register] [--home DIR] [--yes]

Installs global opencode agents (planner, executor), a run-agent.sh session
glue script, and a spec-kit workflow (adr-pipeline) under
~/.config/spec-kit-llm-client/. See README.md for usage.

Options:
  --update       reinstall templates and print newly available config options
  --uninstall    remove installed files (keeps your config.yml)
  --register     install the workflow by ID into the current Spec Kit project
  --home DIR     base directory instead of the real home (used by tests)
  --yes          answer yes to all prompts
"""

import sys

from sklc.cli import main

if __name__ == "__main__":
    sys.exit(main())
