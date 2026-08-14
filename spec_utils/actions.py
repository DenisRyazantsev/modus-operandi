"""Lifecycle actions: register the workflow, uninstall, confirmation prompts."""

from __future__ import annotations

import contextlib
from pathlib import Path

from . import InstallError, Paths, deps


def confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def do_register(paths: Paths) -> None:
    if not paths["workflow"].exists():
        raise InstallError("adr-pipeline.yml not found - run install.py first")
    if not paths["review_workflow"].exists():
        raise InstallError("review-pipeline.yml not found - run install.py first")
    specify = deps.find_in_path("specify")
    if not specify:
        raise InstallError("'specify' not found on PATH - run install.py first")
    if not Path(".specify").exists():
        raise InstallError(
            "not a Spec Kit project (no .specify/ directory); run 'specify init' first"
        )
    for name, path in (
        ("adr-pipeline", paths["workflow"]),
        ("review-pipeline", paths["review_workflow"]),
    ):
        deps.run([specify, "workflow", "add", str(path), "--dev"])
        print(f"installed '{name}' into this project")
    print('run them with: specify workflow run adr-pipeline -i feature="..."')
    print("or: specify workflow run review-pipeline (reviews uncommitted changes)")


def _uninstall_pip_package(package: str) -> bool:
    attempts: list[list[str]] = []
    python = deps.find_in_path("python3")
    if python and deps.pip_works(python):
        attempts.append([python, "-m", "pip", "uninstall", "-y", package])
    pip3 = deps.find_in_path("pip3")
    if pip3:
        attempts.append([pip3, "uninstall", "-y", package])
        attempts.append([pip3, "uninstall", "-y", "--user", package])
    for cmd in attempts:
        result = deps.run(cmd, check=False)
        if result.returncode == 0:
            return True
    return False


def do_uninstall(paths: Paths, yes: bool) -> None:
    removed: list[str] = []
    for path in (
        paths["agents"] / "planner.md",
        paths["agents"] / "executor.md",
        paths["run_agent"],
        paths["run_pipeline"],
        paths["save_adr"],
        paths["workflow"],
        paths["review_workflow"],
        paths["config_example"],
    ):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    if removed:
        print("removed:\n  " + "\n  ".join(removed))
    for directory in (paths["agents"], paths["scripts"], paths["config_dir"]):
        with contextlib.suppress(OSError):
            directory.rmdir()
    print("kept your configuration: {}".format(paths["config"]))
    if yes or confirm("uninstall specify-cli? [y/N] "):
        uv = deps.find_in_path("uv")
        if uv and deps.get_specify_version():
            deps.run([uv, "tool", "uninstall", "specify-cli"], check=False)
    if yes or confirm("uninstall PyYAML? [y/N] "):
        _uninstall_pip_package("pyyaml")
