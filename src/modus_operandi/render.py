"""Rendering: install the pipeline artifacts into the target config base.

No template system: the installed scripts are plain static files copied from
the package data (``data/pipeline_scripts/``), the agents are written as
data (frontmatter values are concatenated into the markdown; the role bodies
live as package data under ``data/roles/``), and the workflows are generated
as data (YAML loaded into a dict, the configurable numbers written in,
dumped back). Nothing is substituted into text with placeholders or ``$``
escapes.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import yaml

from . import Paths, config

# The package data root, resolved through importlib.resources so the
# rendered sources work in an installed wheel (no checkout paths).
_DATA = files("modus_operandi").joinpath("data")

# ---------------------------------------------------------------------------
# Agents (frontmatter values written as data into the markdown)
# ---------------------------------------------------------------------------


def _role_body(name: str) -> str:
    """The role prompt body, read from package data (content as data, never
    in code — same rule as the prompt files under data/prompts/)."""
    return _DATA.joinpath("roles", f"{name}.md").read_text(encoding="utf-8")


def _agent_markdown(
    description: str,
    temperature: str,
    provider: str,
    model: str,
    reasoning: str,
    body: str,
) -> str:
    # The frontmatter values are data: plain string concatenation (no
    # placeholder machinery), so the body can contain any characters.
    frontmatter = (
        "---\n"
        "description: " + description + "\n"
        "mode: primary\n"
        "model: " + provider + "/" + model + "\n"
        "temperature: " + temperature + "\n"
        "reasoningEffort: " + reasoning + "\n"
        'permission:\n  "*": allow\n'
        "---\n"
    )
    return frontmatter + body


def render_agents(cfg: dict[str, Any], paths: Paths) -> None:
    # Agent files are an opencode concept: when the opencode models are not
    # complete (a cursor-only config, or an empty/incomplete section), nothing
    # is written here. When they are present, the files render regardless of
    # the active backend (switching backends must not require a reinstall).
    # check_files() requires the files under the same predicate.
    if not config.opencode_models_complete(cfg):
        return
    models = (cfg.get("opencode") or {}).get("models") or {}
    planner = models["planner"]
    executor = models["executor"]
    (paths["agents"] / "planner.md").write_text(
        _agent_markdown(
            "Planner and reviewer for the modus-operandi task/review workflows",
            "0.3",
            planner["provider"],
            planner["model"],
            planner["reasoning"],
            _role_body("planner"),
        ),
        encoding="utf-8",
    )
    (paths["agents"] / "executor.md").write_text(
        _agent_markdown(
            "Executor for the modus-operandi task/review workflows",
            "0.1",
            executor["provider"],
            executor["model"],
            executor["reasoning"],
            _role_body("executor"),
        ),
        encoding="utf-8",
    )


def render_role_bodies(paths: Paths) -> None:
    # The role bodies as plain text next to run-agent.sh, read from the same
    # package data as the opencode agent files (single source of truth).
    # run-agent.sh prefixes the role body to the FIRST message of a fresh
    # cursor chat; opencode carries the role in the agent files instead.
    (paths["planner_body"]).write_text(_role_body("planner"), encoding="utf-8")
    (paths["executor_body"]).write_text(_role_body("executor"), encoding="utf-8")


# ---------------------------------------------------------------------------
# Static scripts (copied verbatim; settings come from args/env at runtime)
# ---------------------------------------------------------------------------


def _install_script(source_name: str, target: Any, executable: bool = False) -> None:
    data = _DATA.joinpath("pipeline_scripts", source_name).read_bytes()
    target.write_bytes(data)
    if executable:
        target.chmod(0o755)


def render_run_agent(paths: Paths) -> None:
    _install_script("run-agent.sh", paths["run_agent"], executable=True)
    # run-agent.sh is split one concern per file: session_store.sh and
    # run-agent-cursor.sh are sourced (no exec bit needed), prompt_subst.sh
    # is called as a helper and must be executable.
    for key, source_name in (
        ("session_store", "session_store.sh"),
        ("run_agent_cursor", "run-agent-cursor.sh"),
    ):
        _install_script(source_name, paths[key])
    _install_script("prompt_subst.sh", paths["prompt_subst"], executable=True)


def render_name_task(paths: Paths) -> None:
    _install_script("name-task.sh", paths["name_task"], executable=True)


def render_run_pipeline(paths: Paths) -> None:
    # run-pipeline.py is split one class per file; the modules below must all
    # be copied together so the installed wrapper stays importable.
    _install_script("run_pipeline.py", paths["run_pipeline"], executable=True)
    for key, source_name in (
        ("engine_output", "engine_output.py"),
        ("feedback_gate", "feedback_gate.py"),
        ("display", "display.py"),
        ("run_state", "run_state.py"),
        ("workflow_info", "workflow_info.py"),
        ("run_id_discoverer", "run_id_discoverer.py"),
        ("step_result_poller", "step_result_poller.py"),
        ("agent_log_tailer", "agent_log_tailer.py"),
        ("gate_state", "gate_state.py"),
        ("buffered_emitter", "buffered_emitter.py"),
        ("live_monitor", "live_monitor.py"),
        ("live_lines", "live_lines.py"),
        ("table_format", "table_format.py"),
        ("usage_parser", "usage_parser.py"),
        ("config_invocation", "config_invocation.py"),
        ("run_statistics", "run_statistics.py"),
        ("latency_table", "latency_table.py"),
        ("notify", "notify.py"),
        ("feedback_editor", "feedback_editor.py"),
        ("pty_spawn", "pty_spawn.py"),
        # The shared editor resolution, copied next to the wrapper too.
        ("editor", "editor.py"),
    ):
        _install_script(source_name, paths[key])


def render_victory_wav(paths: Paths) -> None:
    # Static asset shipped next to the installed run-pipeline.py, which
    # resolves it from its own location at runtime.
    paths["victory_wav"].write_bytes(_DATA.joinpath("victory.wav").read_bytes())


def render_adr_scripts(paths: Paths) -> None:
    # save_adr.py imports task_utils.py, adr_utils.py and agent_call.py, and
    # check_review.py / check_questions.py import task_utils.py, so all seven
    # scripts must be copied together to stay importable from scripts/.
    for key in (
        "task_utils",
        "check_review",
        "check_implementation",
        "check_questions",
        "save_adr",
        "adr_utils",
        "agent_call",
    ):
        _install_script(f"{key}.py", paths[key])


# The workflow step scripts, one per shell step (CONTRIBUTING.md: the
# workflows carry no bash - every step calls exactly one of these). The
# .sh ones are invoked directly and must be executable; validate_inputs.py
# is called through python3.
_STEP_SCRIPTS = {
    "agent_step": ("agent-step.sh", True),
    "review_check": ("review-check.sh", True),
    "warm_planner": ("warm-planner.sh", True),
    "determine_scope": ("determine-scope.sh", True),
    "review_task_id": ("review-task-id.sh", True),
    "adr_task_id": ("adr-task-id.sh", True),
    "implement_retry": ("implement-retry.sh", True),
    "clear_feedback": ("clear-feedback.sh", True),
    "implement_pass_check": ("implement-pass-check.sh", True),
    "pass_check": ("pass-check.sh", True),
    "show_file": ("show-file.sh", True),
    "validate_inputs": ("validate_inputs.py", False),
    "check_plan_deviation": ("check_plan_deviation.py", False),
}


def render_step_scripts(paths: Paths) -> None:
    for key, (source_name, executable) in _STEP_SCRIPTS.items():
        _install_script(source_name, paths[key], executable=executable)


# ---------------------------------------------------------------------------
# Workflows (static sources; only the six config numbers are written as data)
# ---------------------------------------------------------------------------

# Loop step id -> config key for the max-iteration ceiling. The engine only
# accepts a literal integer for max_iterations (no expressions), so the
# configured values are written into the workflow at install/`modus-operandi edit`
# time.
# The four per-kind review loops were replaced by the single parallel
# review-fix-loop (ADR-0009); the legacy per-check config keys
# (max_srp_iterations / max_bug_iterations / max_comment_iterations) stay in
# the config for backward compatibility but no longer bind any loop.
_LOOP_ITERATION_KEYS = {
    "implement-loop": "max_implement_iterations",
    "review-fix-loop": "max_fix_iterations",
    "executor-questions-loop": "max_questions_iterations",
}


def _patch_workflow_numbers(data: dict[str, Any], cfg: dict[str, Any]) -> None:
    """Write shell_timeout and the max_*_iterations values into the workflow.

    The static sources carry the default literals; this overwrites them from
    the validated config so `modus-operandi edit` re-applies a changed config
    without any text-substitution machinery.
    """
    workflow_cfg = cfg["workflow"]
    timeout = workflow_cfg["shell_timeout"]

    def walk(steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if "timeout" in step:
                step["timeout"] = timeout
            if step.get("type") == "do-while":
                step_id = step.get("id")
                key = _LOOP_ITERATION_KEYS.get(step_id) if isinstance(step_id, str) else None
                if key:
                    step["max_iterations"] = workflow_cfg[key]
            for branch in ("steps", "then", "else"):
                nested = step.get(branch)
                if isinstance(nested, list):
                    walk(nested)
            # A fan-out step's nested `step:` template is a step in its own
            # right (one shell step per item) and must be patched too.
            fan = step.get("step")
            if isinstance(fan, dict):
                walk([fan])

    walk(data["steps"])


def _generate_workflow(source_name: str, cfg: dict[str, Any]) -> str:
    source = _DATA.joinpath("workflows", f"{source_name}.yml")
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    _patch_workflow_numbers(data, cfg)
    return str(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False))


def render_review_workflow(cfg: dict[str, Any], paths: Paths) -> None:
    paths["review_workflow"].write_text(
        _generate_workflow("review-pipeline", cfg), encoding="utf-8"
    )


def render_task_workflow(cfg: dict[str, Any], paths: Paths) -> None:
    paths["task_workflow"].write_text(_generate_workflow("task-pipeline", cfg), encoding="utf-8")


def render_prompts(paths: Paths) -> None:
    # The workflow steps pass the prompt files to run-agent.sh via
    # --prompt-file, which substitutes @TOKEN@ placeholders from the env.
    # Copied verbatim, keeping the review/ and adr/ subdirectories.
    target = paths["prompts"]
    target.mkdir(parents=True, exist_ok=True)
    for rel in _walk_files(_DATA.joinpath("prompts")):
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_DATA.joinpath("prompts", rel).read_bytes())


def _walk_files(node: Any, prefix: str = "") -> list[str]:
    """Recursively list the files under a resources Traversable."""
    found: list[str] = []
    for child in node.iterdir():
        rel = f"{prefix}/{child.name}" if prefix else child.name
        if child.is_dir():
            found.extend(_walk_files(child, rel))
        else:
            found.append(rel)
    return found
