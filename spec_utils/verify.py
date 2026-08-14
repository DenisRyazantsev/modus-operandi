"""Verification of an installed pipeline (files, workflow syntax, agents)."""

from __future__ import annotations

import os
import re

from . import InstallError, Paths, deps


def check_files(paths: Paths) -> list[str]:
    errors: list[str] = []
    for agent_name in ("planner.md", "executor.md"):
        agent = paths["agents"] / agent_name
        if not agent.exists():
            errors.append(f"generated agent missing: {agent}")
    if not paths["save_adr"].exists():
        errors.append("generated script missing: {}".format(paths["save_adr"]))
    if not os.access(paths["run_agent"], os.X_OK):
        errors.append("run-agent.sh is not executable: {}".format(paths["run_agent"]))
    if not os.access(paths["run_pipeline"], os.X_OK):
        errors.append(
            "run-pipeline.sh is not executable: {}".format(paths["run_pipeline"])
        )
    for _, path in (
        ("adr-pipeline.yml", paths["workflow"]),
        ("review-pipeline.yml", paths["review_workflow"]),
    ):
        if not path.exists():
            errors.append(f"generated workflow missing: {path}")
    return errors


def check_workflow_syntax(paths: Paths) -> list[str]:
    # ensure_specify() may end with the binary installed but off PATH (it only
    # warns). Resolve specify explicitly so this check returns a readable error
    # string instead of raising FileNotFoundError, which would abort
    # verify_install() before the remaining checks can run.
    specify = deps.find_in_path("specify")
    if not specify:
        _, binary = deps.latest_specify_version()
        hint = f" (installed at {binary}, add it to PATH)" if binary else ""
        return [
            f"'specify' not found on PATH{hint}; add it to PATH and rerun install.py"
        ]
    # `specify workflow info <path>` parses and renders the workflow graph
    # without executing it. That is the syntax probe: a valid workflow exits 0.
    # (The old probe ran `specify workflow run` expecting a "required input"
    # error - it cannot be used for review-pipeline, which has no inputs, since
    # the run would actually execute.)
    errors: list[str] = []
    for wf_name, path in (
        ("adr-pipeline.yml", paths["workflow"]),
        ("review-pipeline.yml", paths["review_workflow"]),
    ):
        result = deps.run([specify, "workflow", "info", str(path)], check=False)
        if result.returncode != 0:
            errors.append(
                f"{wf_name} syntax check failed:\n"
                + (result.stderr or result.stdout).strip()
            )
    return errors


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
