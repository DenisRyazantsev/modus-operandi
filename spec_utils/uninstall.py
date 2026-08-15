"""Uninstall: remove installed files and optionally the dependencies."""

from __future__ import annotations

import contextlib
import shutil

from . import Paths, deps, prompt


def do_uninstall(paths: Paths, yes: bool) -> None:
    removed: list[str] = []
    for path in (
        paths["agents"] / "planner.md",
        paths["agents"] / "executor.md",
        paths["run_agent"],
        paths["name_task"],
        paths["run_pipeline"],
        paths["run_pipeline_common"],
        paths["run_id_discoverer"],
        paths["step_result_poller"],
        paths["agent_log_tailer"],
        paths["gate_state"],
        paths["buffered_emitter"],
        paths["live_monitor"],
        paths["victory_wav"],
        paths["save_adr"],
        paths["check_review"],
        paths["check_implementation"],
        paths["task_utils"],
        paths["adr_utils"],
        paths["agent_call"],
        paths["workflow"],
        paths["review_workflow"],
        paths["config_example"],
        paths["install_path"],
        paths["spec_run"],
    ):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    exceptions_dir = paths["exceptions_dir"]
    if exceptions_dir.is_dir():
        shutil.rmtree(exceptions_dir)
        removed.append(str(exceptions_dir))
    prompts = paths["prompts"]
    if prompts.is_dir():
        shutil.rmtree(prompts)
        removed.append(str(prompts))
    if removed:
        print("removed:\n  " + "\n  ".join(removed))
    for directory in (paths["agents"], paths["scripts"], paths["config_dir"], paths["user_bin"]):
        with contextlib.suppress(OSError):
            directory.rmdir()
    print("kept your configuration: {}".format(paths["config"]))
    if yes or prompt.confirm("uninstall specify-cli? [y/N] "):
        deps.uninstall_specify()
    if yes or prompt.confirm("uninstall PyYAML? [y/N] "):
        deps.uninstall_pyyaml()
