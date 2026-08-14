"""Uninstall: remove installed files and optionally the dependencies."""

from __future__ import annotations

import contextlib

from . import Paths, deps, prompt


def do_uninstall(paths: Paths, yes: bool) -> None:
    removed: list[str] = []
    for path in (
        paths["agents"] / "planner.md",
        paths["agents"] / "executor.md",
        paths["run_agent"],
        paths["name_task"],
        paths["run_pipeline"],
        paths["save_adr"],
        paths["check_review"],
        paths["task_utils"],
        paths["adr_utils"],
        paths["agent_call"],
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
    if yes or prompt.confirm("uninstall specify-cli? [y/N] "):
        deps.uninstall_specify()
    if yes or prompt.confirm("uninstall PyYAML? [y/N] "):
        deps.uninstall_pyyaml()
