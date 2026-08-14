"""Verification of an installed pipeline (files, workflow syntax, agents)."""

from __future__ import annotations

import os
import re
import tempfile

from . import InstallError
from . import deps


def validate_install(paths):
    for name in ("planner.md", "executor.md"):
        agent = paths["agents"] / name
        if not agent.exists():
            raise InstallError("generated agent missing: %s" % agent)
    if not os.access(paths["run_agent"], os.X_OK):
        raise InstallError("run-agent.sh is not executable: %s" % paths["run_agent"])

    with tempfile.TemporaryDirectory() as tmp:
        result = deps.run(
            ["specify", "workflow", "run", str(paths["workflow"]), "--json"],
            cwd=tmp,
            check=False,
        )
        combined = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
        if result.returncode == 0 or "required input" not in combined:
            raise InstallError(
                "workflow syntax check failed:\n%s"
                % ((result.stderr or result.stdout).strip())
            )

    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(paths["agents"].parent.parent)
    result = deps.run(["opencode", "agent", "list"], check=False, env=env)
    if result.returncode != 0:
        raise InstallError("opencode agent list failed: %s" % result.stderr.strip())
    names = set(
        re.findall(r"^(\S+)\s+\((?:primary|subagent)\)", result.stdout, re.M)
    )
    for name in ("planner", "executor"):
        if name not in names:
            raise InstallError(
                "opencode does not see the '%s' agent; check %s"
                % (name, paths["agents"])
            )
