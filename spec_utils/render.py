"""Rendering: install the pipeline artifacts into the target home directory.

No template system: the installed scripts are plain static files copied from
``pipeline_scripts/``, the agents are written as data (frontmatter values are
concatenated into the markdown), and the workflows are generated as data
(YAML loaded into a dict, the six configurable numbers written in, dumped
back). Nothing is substituted into text with placeholders or ``$`` escapes.
"""

# ruff: noqa: E501  (the agent bodies below are single-line prompt paragraphs)
from __future__ import annotations

import shutil
from typing import Any

from . import (
    PIPELINE_SCRIPTS_DIR,
    REPO_ROOT,
    WORKFLOWS_DIR,
    Paths,
    config,
    yaml_loader,
)

# ---------------------------------------------------------------------------
# Agents (frontmatter values written as data into the markdown)
# ---------------------------------------------------------------------------

PLANNER_BODY = """You are the planner and reviewer in a spec-driven "planner -> executor" pipeline. You run on a strong model; the executor runs on a cheap one. You never write application code yourself.

A task is identified by an id `<task-id>`; all its artifacts live under `.workflow/tasks/<task-id>/` inside the project. You are given the concrete paths in each prompt.

## Duties

1. **Write ADRs.** When asked to plan a feature, write the ADR file (`.workflow/tasks/<task-id>/adr.md`) with YAML frontmatter (`slug`, `status: accepted`, `date`) followed by sections: Context, Decision, Alternatives, Consequences, Acceptance Criteria. The frontmatter MUST include a `slug` field: a short 2-3 word summary of the ADR in ENGLISH, lowercase kebab-case (e.g. `slug: prod-validation-splits`). Write it on its own line right after the opening `---`. The pipeline fails if it is missing or empty — do not skip it even when the ADR body is written in Russian. Ground the decision in the described feature, be specific enough for a cheap model to implement without re-asking, and keep it minimal.
2. **Answer executor questions.** When asked, read `.workflow/tasks/<task-id>/questions.md`. If its first line is exactly `QUESTIONS: PRESENT`, write `.workflow/tasks/<task-id>/answers.md`, answering each question line-by-line in the same order. If the first line is exactly `QUESTIONS: NONE`, write nothing.
3. **Review.** When asked to review, inspect the current git changes against `.workflow/tasks/<task-id>/adr.md` using `git diff HEAD` (this includes staged changes; run `git status` first to see what changed). Write `.workflow/tasks/<task-id>/review-N.md`, where N is the next number after the existing review files (`review-1.md`, `review-2.md`, ...). The first line must be exactly `VERDICT: PASS` or `VERDICT: FIX`, followed by concrete, actionable findings. Findings must map to acceptance criteria or explicit ADR requirements. The verdict must reflect the implemented code, not the ADR document itself.

Do not implement features. Do not invent requirements beyond the ADR. Prefer your session context over re-reading files you already loaded."""

EXECUTOR_BODY = """You are the executor in a spec-driven "planner -> executor" pipeline. You run on a cheap model; the planner runs on a strong one. You implement features from written artifacts; you do not design architecture on your own.

A task is identified by an id `<task-id>`; all its artifacts live under `.workflow/tasks/<task-id>/` inside the project. You are given the concrete paths in each prompt.

## Duties

1. **Read the plan.** Start from `.workflow/tasks/<task-id>/adr.md`. If `.workflow/tasks/<task-id>/answers.md` exists, read it too.
2. **Ask when uncertain.** If anything in the plan is ambiguous or underspecified, write `.workflow/tasks/<task-id>/questions.md` whose first line is exactly `QUESTIONS: PRESENT`, followed by numbered questions, then STOP — do not implement anything. If everything is clear, still write `.workflow/tasks/<task-id>/questions.md` with the first line exactly `QUESTIONS: NONE`.
3. **Implement.** Follow adr.md and answers.md exactly. Prefer minimal, idiomatic changes. Do not add unrequested features.
4. **Fix findings.** When asked to fix, read the latest `.workflow/tasks/<task-id>/review-N.md` (the highest N) and address only its findings.
5. **Verify.** Before finishing, run the project's tests/linter if any are present.

Do not re-read the whole project when its context is already in your session. Keep changes scoped to the plan."""


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
            "Planner and reviewer for the adr-pipeline workflow",
            "0.3",
            planner["provider"],
            planner["model"],
            planner["reasoning"],
            PLANNER_BODY,
        ),
        encoding="utf-8",
    )
    (paths["agents"] / "executor.md").write_text(
        _agent_markdown(
            "Executor for the adr-pipeline workflow",
            "0.1",
            executor["provider"],
            executor["model"],
            executor["reasoning"],
            EXECUTOR_BODY,
        ),
        encoding="utf-8",
    )


def render_role_bodies(paths: Paths) -> None:
    # The role bodies as plain text next to run-agent.sh, written from the
    # same constants as the opencode agent files (single source of truth).
    # run-agent.sh prefixes the role body to the FIRST message of a fresh
    # cursor chat; opencode carries the role in the agent files instead.
    (paths["planner_body"]).write_text(PLANNER_BODY, encoding="utf-8")
    (paths["executor_body"]).write_text(EXECUTOR_BODY, encoding="utf-8")


# ---------------------------------------------------------------------------
# Static scripts (copied verbatim; settings come from args/env at runtime)
# ---------------------------------------------------------------------------


def _install_script(source_name: str, target: Any, executable: bool = False) -> None:
    shutil.copy2(PIPELINE_SCRIPTS_DIR / source_name, target)
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
    # be copied together so the installed wrapper stays importable. The path
    # key of the shared module differs from its filename (leading underscore).
    _install_script("run_pipeline.py", paths["run_pipeline"], executable=True)
    for key, source_name in (
        ("run_pipeline_common", "_run_pipeline_common.py"),
        ("run_id_discoverer", "run_id_discoverer.py"),
        ("step_result_poller", "step_result_poller.py"),
        ("agent_log_tailer", "agent_log_tailer.py"),
        ("gate_state", "gate_state.py"),
        ("buffered_emitter", "buffered_emitter.py"),
        ("live_monitor", "live_monitor.py"),
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


def render_spec_run(paths: Paths) -> None:
    _install_script("spec_run.py", paths["spec_run"], executable=True)
    # spec-run is split one class per file: the exceptions package, the
    # edit command and the shared editor module are copied next to the
    # launcher so the submodules stay importable.
    paths["exceptions_dir"].mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "help_requested.py", "invalid_invocation.py", "edit_requested.py"):
        shutil.copy2(PIPELINE_SCRIPTS_DIR / "exceptions" / name, paths["exceptions_dir"] / name)
    shutil.copy2(PIPELINE_SCRIPTS_DIR / "edit_command.py", paths["edit_command"])
    shutil.copy2(PIPELINE_SCRIPTS_DIR / "editor.py", paths["launcher_editor"])


def render_victory_wav(paths: Paths) -> None:
    # Static asset shipped next to the installed run-pipeline.py, which
    # resolves it from its own location at runtime.
    shutil.copy2(REPO_ROOT / "architecture" / "assets" / "victory.wav", paths["victory_wav"])


def render_adr_scripts(paths: Paths) -> None:
    # save_adr.py imports task_utils.py, adr_utils.py and agent_call.py, and
    # check_review.py imports task_utils.py, so all six scripts must be copied
    # together to stay importable from scripts/.
    for key in (
        "task_utils",
        "check_review",
        "check_implementation",
        "save_adr",
        "adr_utils",
        "agent_call",
    ):
        shutil.copy2(PIPELINE_SCRIPTS_DIR / f"{key}.py", paths[key])


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
    "sync_adr_step": ("sync-adr.sh", True),
    "clear_feedback": ("clear-feedback.sh", True),
    "implement_pass_check": ("implement-pass-check.sh", True),
    "pass_check": ("pass-check.sh", True),
    "validate_inputs": ("validate_inputs.py", False),
}


def render_step_scripts(paths: Paths) -> None:
    for key, (source_name, executable) in _STEP_SCRIPTS.items():
        _install_script(source_name, paths[key], executable=executable)


# ---------------------------------------------------------------------------
# Workflows (static sources; only the six config numbers are written as data)
# ---------------------------------------------------------------------------

# Loop step id -> config key for the max-iteration ceiling. The engine only
# accepts a literal integer for max_iterations (no expressions), so the
# configured values are written into the workflow at install/--apply time.
# The four per-kind review loops were replaced by the single parallel
# review-fix-loop (ADR-0009); the legacy per-check config keys
# (max_srp_iterations / max_bug_iterations / max_comment_iterations) stay in
# the config for backward compatibility but no longer bind any loop.
_LOOP_ITERATION_KEYS = {
    "adr-loop": "max_adr_iterations",
    "implement-loop": "max_implement_iterations",
    "review-fix-loop": "max_fix_iterations",
}


def _patch_workflow_numbers(data: dict[str, Any], cfg: dict[str, Any]) -> None:
    """Write shell_timeout and the max_*_iterations values into the workflow.

    The static sources carry the default literals; this overwrites them from
    the validated config so `spec-run edit`/`--apply` re-applies a changed
    config without any text-substitution machinery.
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
    source = WORKFLOWS_DIR / f"{source_name}.yml"
    data = yaml_loader.yaml.safe_load(source.read_text(encoding="utf-8"))
    _patch_workflow_numbers(data, cfg)
    return str(
        yaml_loader.yaml.safe_dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
    )


def render_workflow(cfg: dict[str, Any], paths: Paths) -> None:
    paths["workflow"].write_text(
        _generate_workflow("adr-pipeline", cfg), encoding="utf-8"
    )


def render_review_workflow(cfg: dict[str, Any], paths: Paths) -> None:
    paths["review_workflow"].write_text(
        _generate_workflow("review-pipeline", cfg), encoding="utf-8"
    )


def render_prompts(paths: Paths) -> None:
    # The workflow steps pass the prompt files to run-agent.sh via
    # --prompt-file, which substitutes @TOKEN@ placeholders from the env.
    # Copied verbatim, keeping the review/ and adr/ subdirectories.
    source = REPO_ROOT / "prompts"
    target = paths["prompts"]
    target.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_file():
            dest = target / path.relative_to(source)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
