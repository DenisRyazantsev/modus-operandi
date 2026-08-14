"""Lifecycle actions: register the workflow, uninstall, confirmation prompts."""

from __future__ import annotations

from pathlib import Path

from . import InstallError
from . import deps


def confirm(prompt):
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def do_register(paths):
    if not paths["workflow"].exists():
        raise InstallError("adr-pipeline.yml not found - run install.py first")
    specify = deps.find_in_path("specify")
    if not specify:
        raise InstallError("'specify' not found on PATH - run install.py first")
    if not Path(".specify").exists():
        raise InstallError(
            "not a Spec Kit project (no .specify/ directory); run 'specify init' first"
        )
    deps.run([specify, "workflow", "add", str(paths["workflow"]), "--dev"])
    print("installed 'adr-pipeline' into this project")
    print("run it with: specify workflow run adr-pipeline -i feature=\"...\"")


def _uninstall_pip_package(package):
    attempts = []
    python = deps.find_in_path("python3")
    if python and deps._pip_works(python):
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


def do_uninstall(paths, yes):
    removed = []
    for path in (
        paths["agents"] / "planner.md",
        paths["agents"] / "executor.md",
        paths["run_agent"],
        paths["save_adr"],
        paths["workflow"],
        paths["config_example"],
    ):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    if removed:
        print("removed:\n  " + "\n  ".join(removed))
    for directory in (paths["agents"], paths["scripts"], paths["sklc"]):
        try:
            directory.rmdir()
        except OSError:
            pass
    print("kept your configuration: %s" % paths["config"])
    if yes or confirm("uninstall specify-cli? [y/N] "):
        uv = deps.find_in_path("uv")
        if uv and deps.get_specify_version():
            deps.run([uv, "tool", "uninstall", "specify-cli"], check=False)
    if yes or confirm("uninstall PyYAML? [y/N] "):
        _uninstall_pip_package("pyyaml")
