"""Verification of an installed pipeline (files, workflow syntax, agents)."""

from __future__ import annotations

import os
import re
import tempfile

from . import InstallError
from . import deps


def check_files(paths):
    errors = []
    for name in ("planner.md", "executor.md"):
        agent = paths["agents"] / name
        if not agent.exists():
            errors.append("generated agent missing: %s" % agent)
    if not paths["save_adr"].exists():
        errors.append("generated script missing: %s" % paths["save_adr"])
    if not os.access(paths["run_agent"], os.X_OK):
        errors.append("run-agent.sh is not executable: %s" % paths["run_agent"])
    return errors


def check_workflow_syntax(paths):
    with tempfile.TemporaryDirectory() as tmp:
        result = deps.run(
            ["specify", "workflow", "run", str(paths["workflow"]), "--json"],
            cwd=tmp,
            check=False,
        )
        combined = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
        if result.returncode == 0 or "required input" not in combined:
            return [
                "workflow syntax check failed:\n%s"
                % ((result.stderr or result.stdout).strip())
            ]
    return []


def check_agents_visible(paths):
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(paths["agents"].parent.parent)
    result = deps.run(["opencode", "agent", "list"], check=False, env=env)
    if result.returncode != 0:
        return ["opencode agent list failed: %s" % result.stderr.strip()]
    names = set(
        re.findall(r"^(\S+)\s+\((?:primary|subagent)\)", result.stdout, re.M)
    )
    errors = []
    for name in ("planner", "executor"):
        if name not in names:
            errors.append(
                "opencode does not see the '%s' agent; check %s"
                % (name, paths["agents"])
            )
    return errors


def verify_install(paths):
    errors = []
    errors += check_files(paths)
    errors += check_workflow_syntax(paths)
    errors += check_agents_visible(paths)
    if errors:
        raise InstallError(
            "installation check failed:\n  " + "\n  ".join(errors)
        )
