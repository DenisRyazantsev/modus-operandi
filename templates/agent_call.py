#!/usr/bin/env python3
"""agent_call.py - reach a workflow agent through run-agent.sh.

Shared glue for the generated scripts that must invoke the planner or
executor (save_adr.py asking the planner for a missing slug, ...).
run-agent.sh keeps the warm session and logs the call; this module only
builds the list-form argv and runs it, and turns a failed invocation into
a readable error instead of a raw CalledProcessError traceback.
"""

from __future__ import annotations

import subprocess
import sys


def ask_agent(run_agent: str, role: str, prompt: str, task_id: str = "") -> None:
    # list-form invocation (no shell=True) so a run-agent.sh path containing
    # spaces survives as a single argv element.
    cmd = [run_agent, role, prompt]
    if task_id:
        cmd += ["--task", task_id]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        # run-agent.sh already prints the reason to its stderr ("run-agent:
        # opencode exited N; full log: <path>"); surface the tail of that
        # output so the workflow step fails with a readable message, not a
        # Python traceback that hides the agent's actual error.
        detail = (proc.stderr or proc.stdout or "").strip()
        tail = " | ".join(line.strip() for line in detail.splitlines()[-5:])
        sys.exit(
            f"error: {role} agent call failed (exit {proc.returncode})"
            + (f": {tail}" if tail else "")
        )
