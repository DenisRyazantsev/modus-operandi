#!/usr/bin/env python3
"""Install the spec-kit-llm-client planner/executor pipeline.

Usage:
  python3 install.py [--update] [--apply] [--uninstall] [--home DIR] [--yes]

Installs global opencode agents (planner, executor), a run-agent.sh session
glue script, and a spec-kit workflow (adr-pipeline) under
~/.config/spec-kit-llm-client/. See README.md for usage.

Options:
  --update       reinstall templates and print newly available config options
  --apply        re-render all artifacts from the current config (no
                 prerequisite/dependency checks, no next-steps; used by
                 `spec-run edit` after the editor closes)
  --uninstall    remove installed files (keeps your config.yml)
  --home DIR     base directory instead of the real home (used by tests)
  --yes          answer yes to all prompts
"""

import sys

from spec_utils.cli import main

if __name__ == "__main__":
    sys.exit(main())
