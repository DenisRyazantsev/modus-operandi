"""Verification of an installed pipeline (files, workflow syntax, agents)."""

from __future__ import annotations

import os
import re
import tempfile

from . import InstallError, Paths, deps


def check_files(paths: Paths) -> list[str]:
    errors: list[str] = []
    for name in ("planner.md", "executor.md"):
        agent = paths["agents"] / name
        if not agent.exists():
            errors.append(f"generated agent missing: {agent}")
    if not paths["save_adr"].exists():
        errors.append("generated script missing: {}".format(paths["save_adr"]))
    if not os.access(paths["run_agent"], os.X_OK):
        errors.append("run-agent.sh is not executable: {}".format(paths["run_agent"]))
    return errors


def check_workflow_syntax(paths: Paths) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        result = deps.run(
            ["specify", "workflow", "run", str(paths["workflow"]), "--json"],
            cwd=tmp,
            check=False,
        )
        combined = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
        if result.returncode == 0 or "required input" not in combined:
            return [
                f"workflow syntax check failed:\n{(result.stderr or result.stdout).strip()}"
            ]
    return []


def check_agents_visible(paths: Paths) -> list[str]:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(paths["agents"].parent.parent)
    result = deps.run(["opencode", "agent", "list"], check=False, env=env)
    if result.returncode != 0:
        return [f"opencode agent list failed: {result.stderr.strip()}"]
    names = set(
        re.findall(r"^(\S+)\s+\((?:primary|subagent)\)", result.stdout, re.M)
    )
    errors: list[str] = []
    for name in ("planner", "executor"):
        if name not in names:
            errors.append(
                "opencode does not see the '{}' agent; check {}".format(name, paths["agents"])
            )
    return errors


def verify_install(paths: Paths) -> None:
    errors: list[str] = []
    errors += check_files(paths)
    errors += check_workflow_syntax(paths)
    errors += check_agents_visible(paths)
    if errors:
        raise InstallError(
            "installation check failed:\n  " + "\n  ".join(errors)
        )
