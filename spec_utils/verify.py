"""Verification: prerequisites, installed pipeline files, workflow syntax, agents."""

from __future__ import annotations

import os
import re
from typing import Any

from . import InstallError, Paths, config, proc, tool_discovery, versions


def _config_backend(paths: Paths) -> str:
    # check_prerequisites() runs before the config is validated (and before it
    # exists on a fresh install): read only the backend key and degrade to the
    # default on any failure - a malformed config surfaces later in apply().
    try:
        raw = config.load_config(paths["config"])
    except Exception:
        return config.DEFAULT_BACKEND
    backend = raw.get("backend")
    return backend if backend in config.BACKENDS else config.DEFAULT_BACKEND


def check_prerequisites(paths: Paths) -> None:
    # Install-time presence checks: the flow cannot proceed without these
    # tools, so they raise directly (unlike the list-returning checks below,
    # which let verify_install() collect every failure at once). Only the
    # active backend's CLI is required: opencode-only and cursor-only installs
    # are both supported.
    if not tool_discovery.find_in_path("python3"):
        raise InstallError("python3 not found in PATH")
    if _config_backend(paths) == "cursor":
        if not (
            tool_discovery.find_in_path("cursor-agent")
            or tool_discovery.find_in_path("agent")
        ):
            raise InstallError(
                "cursor-agent (or agent) not found in PATH - install the Cursor CLI first "
                "(https://cursor.com/docs/cli)"
            )
    elif not tool_discovery.find_in_path("opencode"):
        raise InstallError(
            "opencode not found in PATH - install it first (https://opencode.ai/docs)"
        )


def check_files(paths: Paths, cfg: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    cfg = cfg or {}
    # Opencode agent files are required under the same predicate that renders
    # them (config.opencode_models_complete): an opencode backend always has
    # them, while a cursor-only config with an empty/incomplete opencode
    # section neither renders nor demands them.
    require_agents = config.opencode_models_complete(cfg)
    if require_agents:
        for agent_name in ("planner.md", "executor.md"):
            agent = paths["agents"] / agent_name
            if not agent.exists():
                errors.append(f"generated agent missing: {agent}")
    for key in (
        "save_adr",
        "check_review",
        "check_implementation",
        "check_questions",
        "task_utils",
        "adr_utils",
        "agent_call",
        "validate_inputs",
    ):
        script = paths[key]
        if not script.exists():
            errors.append(f"generated script missing: {script}")
    # The workflow step scripts (CONTRIBUTING.md: one script call per shell
    # step): the .sh ones are invoked directly and must be executable.
    for key, executable in (
        ("agent_step", True),
        ("review_check", True),
        ("warm_planner", True),
        ("determine_scope", True),
        ("review_task_id", True),
        ("adr_task_id", True),
        ("implement_retry", True),
        ("sync_adr_step", True),
        ("clear_feedback", True),
        ("implement_pass_check", True),
        ("pass_check", True),
        ("show_file", True),
    ):
        script = paths[key]
        if not script.is_file():
            errors.append(f"generated step script missing: {script}")
        elif executable and not os.access(script, os.X_OK):
            errors.append(f"step script is not executable: {script}")
    if not os.access(paths["run_agent"], os.X_OK):
        errors.append("run-agent.sh is not executable: {}".format(paths["run_agent"]))
    if not os.access(paths["name_task"], os.X_OK):
        errors.append("name-task.sh is not executable: {}".format(paths["name_task"]))
    if not os.access(paths["prompt_subst"], os.X_OK):
        errors.append("prompt_subst.sh is not executable: {}".format(paths["prompt_subst"]))
    for key in ("session_store", "run_agent_cursor"):
        if not paths[key].is_file():
            errors.append(f"generated script missing: {paths[key]}")
    if not os.access(paths["run_pipeline"], os.X_OK):
        errors.append("run-pipeline.py is not executable: {}".format(paths["run_pipeline"]))
    for key in (
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
    ):
        if not paths[key].is_file():
            errors.append(f"generated script missing: {paths[key]}")
    if not os.access(paths["spec_run"], os.X_OK):
        errors.append("spec-run is not executable: {}".format(paths["spec_run"]))
    for key in ("edit_command", "launcher_editor"):
        if not paths[key].is_file():
            errors.append(f"generated script missing: {paths[key]}")
    for name in ("__init__.py", "help_requested.py", "invalid_invocation.py", "edit_requested.py"):
        if not (paths["exceptions_dir"] / name).is_file():
            errors.append(f"generated script missing: {paths['exceptions_dir'] / name}")
    if not paths["victory_wav"].is_file():
        errors.append(f"victory sound missing: {paths['victory_wav']}")
    for key in ("planner_body", "executor_body"):
        if not paths[key].is_file():
            errors.append(f"generated role body missing: {paths[key]}")
    for rel in (
        "review/srp-review.md",
        "review/srp-rereview.md",
        "review/bug-review.md",
        "review/bug-rereview.md",
        "review/review.md",
        "review/review-rereview.md",
        "review/comment-review.md",
        "review/comment-rereview.md",
        "review/warmup.md",
        "review/comment-fix.md",
        "adr/write-adr.md",
        "adr/adr-revise.md",
        "adr/executor-questions.md",
        "adr/planner-answers.md",
        "adr/implement.md",
        "adr/implement-retry.md",
        "adr/sync-adr.md",
        "adr/srp-review.md",
        "adr/bug-review.md",
        "adr/review.md",
        "adr/comment-review.md",
        "adr/comment-fix.md",
        "srp-fix.md",
        "bug-fix.md",
        "fix.md",
        "fix-all.md",
    ):
        if not (paths["prompts"] / rel).is_file():
            errors.append(f"generated prompt missing: {paths['prompts'] / rel}")
    for _, path in (
        ("adr-pipeline.yml", paths["workflow"]),
        ("review-pipeline.yml", paths["review_workflow"]),
        ("task-pipeline.yml", paths["task_workflow"]),
    ):
        if not path.exists():
            errors.append(f"generated workflow missing: {path}")
    return errors


def check_workflow_syntax(paths: Paths) -> list[str]:
    # ensure_specify() may end with the binary installed but off PATH (it only
    # warns). Resolve specify explicitly so this check returns a readable error
    # string instead of raising FileNotFoundError, which would abort
    # verify_install() before the remaining checks can run.
    specify = tool_discovery.find_in_path("specify")
    if not specify:
        _, binary = versions.latest_specify_version()
        hint = f" (installed at {binary}, add it to PATH)" if binary else ""
        return [f"'specify' not found on PATH{hint}; add it to PATH and rerun install.py"]
    # `specify workflow info <path>` parses and renders the workflow graph
    # without executing it. That is the syntax probe: a valid workflow exits 0.
    # (The old probe ran `specify workflow run` expecting a "required input"
    # error - it cannot be used for review-pipeline, whose inputs are optional,
    # since the run would actually execute.)
    errors: list[str] = []
    for wf_name, path in (
        ("adr-pipeline.yml", paths["workflow"]),
        ("review-pipeline.yml", paths["review_workflow"]),
        ("task-pipeline.yml", paths["task_workflow"]),
    ):
        result = proc.run([specify, "workflow", "info", str(path)], check=False)
        if result.returncode != 0:
            errors.append(
                f"{wf_name} syntax check failed:\n" + (result.stderr or result.stdout).strip()
            )
    return errors


def check_agents_visible(paths: Paths, cfg: dict[str, Any] | None = None) -> list[str]:
    if (cfg or {}).get("backend") != "opencode":
        # `opencode agent list` only matters for the opencode backend; a
        # cursor-only install may not even have opencode on PATH.
        return []
    env = os.environ.copy()
    # Point opencode at the target config root (~/.config = agents/../..) so
    # `opencode agent list` reports the agents we just installed under --home
    # instead of the real home's config.
    env["XDG_CONFIG_HOME"] = str(paths["agents"].parent.parent)
    result = proc.run(["opencode", "agent", "list"], check=False, env=env)
    if result.returncode != 0:
        return [f"opencode agent list failed: {result.stderr.strip()}"]
    names = set(re.findall(r"^(\S+)\s+\((?:primary|subagent)\)", result.stdout, re.M))
    errors: list[str] = []
    for name in ("planner", "executor"):
        if name not in names:
            errors.append(
                "opencode does not see the '{}' agent; check {}".format(name, paths["agents"])
            )
    return errors


def verify_install(paths: Paths, cfg: dict[str, Any] | None = None) -> None:
    errors: list[str] = []
    errors += check_files(paths, cfg)
    errors += check_workflow_syntax(paths)
    errors += check_agents_visible(paths, cfg)
    if errors:
        raise InstallError("installation check failed:\n  " + "\n  ".join(errors))
