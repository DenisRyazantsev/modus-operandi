"""Uninstall: remove the installed pipeline files from the machine.

``spec-run uninstall`` is the explicit full-cleanup command (``pip uninstall
spec-run`` cannot touch the rendered files under the config base): it removes
``~/.config/spec-run`` (including the user's config.yml), the spec-run-owned
files under ``~/.config/opencode`` and the legacy launcher leftovers from the
pre-pip install model in ``~/.local/bin``, then prints the hint to remove the
wheel itself.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import shutil
from pathlib import Path

from . import Paths, prompt

# The spec-run-owned files under the scripts dir (one key per installed
# file, mirrors paths.py).
_SCRIPTS_KEYS = (
    "run_agent",
    "name_task",
    "planner_body",
    "executor_body",
    "session_store",
    "run_agent_cursor",
    "prompt_subst",
    "run_pipeline",
    "run_pipeline_common",
    "run_id_discoverer",
    "step_result_poller",
    "agent_log_tailer",
    "gate_state",
    "buffered_emitter",
    "live_monitor",
    "live_lines",
    "usage_parser",
    "config_invocation",
    "run_statistics",
    "latency_table",
    "notify",
    "feedback_editor",
    "pty_spawn",
    "editor",
    "victory_wav",
    "save_adr",
    "check_review",
    "check_implementation",
    "check_questions",
    "task_utils",
    "adr_utils",
    "agent_call",
    "agent_step",
    "review_check",
    "warm_planner",
    "determine_scope",
    "review_task_id",
    "adr_task_id",
    "implement_retry",
    "sync_adr_step",
    "clear_feedback",
    "implement_pass_check",
    "pass_check",
    "show_file",
    "validate_inputs",
)

# Legacy launcher files the old install model rendered into ~/.local/bin;
# cleaned up so `spec-run uninstall` fully clears a machine installed before
# the pip model. The live pip console script (pip install --user) is
# detected and kept — pip uninstall removes it together with the package.
_LEGACY_BIN_NAMES = ("spec-run", "editor.py", "edit_command.py")


def _pip_installed_bin(paths: Paths) -> set[Path]:
    """The ~/.local/bin files owned by the installed spec-run distribution.

    ``pip install --user spec-run`` puts the console script into
    ~/.local/bin and records it in the package RECORD; deleting that file
    while the pip metadata stays would leave the package half-installed.
    The lookup is best-effort: any failure degrades to "no pip-owned files".
    """
    owned: set[Path] = set()
    try:
        dist = importlib.metadata.distribution("spec-run")
    except importlib.metadata.PackageNotFoundError:
        return owned
    for entry in dist.files or []:
        try:
            located = Path(entry.locate())
        except OSError:
            continue
        if located.parent == paths["user_bin"]:
            owned.add(located)
    return owned


def do_uninstall(paths: Paths, yes: bool) -> int:
    """Remove every spec-run-owned file; returns the exit code.

    Deleting ``~/.config/spec-run`` removes the user's config.yml, so the
    removal is confirmed first unless ``--yes`` is given; a declined prompt
    aborts with exit code 1 and removes nothing.
    """
    if not yes:
        ok = prompt.confirm(
            f"remove {paths['config_dir']} (including your config.yml) and "
            f"spec-run files from {paths['agents'].parent.parent}? [y/N] "
        )
        if not ok:
            print("aborted")
            return 1
    pip_owned = _pip_installed_bin(paths)
    removed: list[str] = []
    for path in (
        paths["agents"] / "planner.md",
        paths["agents"] / "executor.md",
        *(paths[key] for key in _SCRIPTS_KEYS),
    ):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    for name in _LEGACY_BIN_NAMES:
        legacy = paths["user_bin"] / name
        if legacy in pip_owned:
            # The live console script of the installed package: pip uninstall
            # removes it together with the wheel; deleting it here would
            # leave the pip metadata pointing at a missing file.
            continue
        if legacy.exists():
            legacy.unlink()
            removed.append(str(legacy))
    legacy_exceptions = paths["user_bin"] / "exceptions"
    if legacy_exceptions.is_dir():
        shutil.rmtree(legacy_exceptions)
        removed.append(str(legacy_exceptions))
    config_dir = paths["config_dir"]
    if config_dir.is_dir():
        shutil.rmtree(config_dir)
        removed.append(str(config_dir))
    if removed:
        print("removed:\n  " + "\n  ".join(removed))
    for directory in (paths["agents"], paths["scripts"], paths["config_dir"]):
        with contextlib.suppress(OSError):
            directory.rmdir()
    if pip_owned:
        print(
            f"kept the pip console scripts in {paths['user_bin']} (owned by the "
            "installed package)"
        )
    print(
        "run `pip uninstall spec-run` to remove the installed package "
        "(including its console script)"
    )
    return 0
