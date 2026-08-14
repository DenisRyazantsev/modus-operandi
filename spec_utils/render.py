"""Rendering: install templates into the target home directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from string import Template
from typing import Any

from . import REPO_ROOT, TEMPLATES_DIR, Paths


def render_file(
    template_path: Path, target_path: Path, mapping: dict[str, str]
) -> None:
    text = Template(template_path.read_text(encoding="utf-8")).substitute(mapping)
    target_path.write_text(text, encoding="utf-8")


def render_agents(cfg: dict[str, Any], paths: Paths) -> None:
    planner = cfg["models"]["planner"]
    executor = cfg["models"]["executor"]
    render_file(
        TEMPLATES_DIR / "planner.md.tpl",
        paths["agents"] / "planner.md",
        {
            "planner_provider": planner["provider"],
            "planner_model": planner["model"],
            "planner_reasoning": planner["reasoning"],
        },
    )
    render_file(
        TEMPLATES_DIR / "executor.md.tpl",
        paths["agents"] / "executor.md",
        {
            "executor_provider": executor["provider"],
            "executor_model": executor["model"],
            "executor_reasoning": executor["reasoning"],
        },
    )


def render_run_agent(cfg: dict[str, Any], paths: Paths) -> None:
    workflow = cfg["workflow"]
    use_serve = workflow["use_serve"]
    serve_attach = "--attach http://localhost:4096" if use_serve else ""
    render_file(
        TEMPLATES_DIR / "run-agent.sh.tpl",
        paths["run_agent"],
        {
            "serve_attach": serve_attach,
            # The configured state_dir becomes the SKLC_STATE_DIR default so
            # session records and tasks/current resolution match the workflow
            # steps, which already use the same configured directory.
            "state_dir": workflow["state_dir"],
        },
    )
    paths["run_agent"].chmod(0o755)


def render_run_pipeline(cfg: dict[str, Any], paths: Paths) -> None:
    # Wrapper that streams specify output with timestamps, prints step results
    # as they complete, tails the per-role agent logs, prints a run-statistics
    # block after the run and plays a victory sound. The agent logs live under
    # the configured state_dir, matching run-agent.sh's SKLC_STATE_DIR
    # default; the sound file is shipped next to the installed wrapper and
    # referenced by its absolute path.
    render_file(
        TEMPLATES_DIR / "run_pipeline.py.tpl",
        paths["run_pipeline"],
        {
            "state_dir": cfg["workflow"]["state_dir"],
            "sound_path": str(paths["victory_wav"]),
        },
    )
    paths["run_pipeline"].chmod(0o755)


def render_victory_wav(paths: Paths) -> None:
    # Static asset shipped next to the installed run-pipeline.py; the rendered
    # wrapper references it through the absolute path rendered as sound_path.
    shutil.copy2(REPO_ROOT / "architecture" / "assets" / "victory.wav", paths["victory_wav"])


def render_name_task(cfg: dict[str, Any], paths: Paths) -> None:
    use_serve = cfg["workflow"]["use_serve"]
    serve_attach = "--attach http://localhost:4096" if use_serve else ""
    render_file(
        TEMPLATES_DIR / "name-task.sh.tpl",
        paths["name_task"],
        {"serve_attach": serve_attach},
    )
    paths["name_task"].chmod(0o755)


def render_adr_scripts(paths: Paths) -> None:
    # save_adr.py imports task_utils.py, adr_utils.py and agent_call.py, and
    # check_review.py imports task_utils.py, so all five scripts must be
    # copied together to stay importable from scripts/.
    for key in ("task_utils", "check_review", "save_adr", "adr_utils", "agent_call"):
        shutil.copy2(TEMPLATES_DIR / f"{key}.py", paths[key])


def render_workflow(cfg: dict[str, Any], paths: Paths) -> None:
    workflow = cfg["workflow"]
    if workflow["human_gates"]:
        # Interactive mode: the ADR gate prompts the human (approve/revise/reject).
        verdict_decl = ""
        approve_verdict = ""
    else:
        # Non-interactive mode: gate verdict is read from a workflow input that
        # defaults to "approve", so the run never pauses at the ADR gate.
        verdict_decl = (
            "  adr_verdict:\n"
            '    type: string\n'
            '    enum: ["", approve, revise, reject]\n'
            '    default: "approve"'
        )
        approve_verdict = "verdict_input: adr_verdict"
    render_file(
        TEMPLATES_DIR / "adr-pipeline.yml.tpl",
        paths["workflow"],
        {
            "run_agent": str(paths["run_agent"]),
            "name_task": str(paths["name_task"]),
            "save_adr": str(paths["save_adr"]),
            "check_review": str(paths["check_review"]),
            "state_dir": workflow["state_dir"],
            "adr_dir": workflow["adr_dir"],
            "step_timeout": str(workflow["shell_timeout"]),
            "verdict_inputs_decl": verdict_decl,
            "approve_adr_verdict": approve_verdict,
            "max_fix_iterations": str(workflow["max_fix_iterations"]),
            "max_srp_iterations": str(workflow["max_srp_iterations"]),
            "max_bug_iterations": str(workflow["max_bug_iterations"]),
            "max_comment_iterations": str(workflow["max_comment_iterations"]),
            "max_adr_iterations": str(workflow["max_adr_iterations"]),
        },
    )


def render_review_workflow(cfg: dict[str, Any], paths: Paths) -> None:
    # The review-only workflow has no inputs and no ADR stage: it diffs the
    # Whole-codebase review by default, or with -i branch-diff=true the changes
    # between the current branch and the default branch; same review loops.
    workflow = cfg["workflow"]
    render_file(
        TEMPLATES_DIR / "review-pipeline.yml.tpl",
        paths["review_workflow"],
        {
            "run_agent": str(paths["run_agent"]),
            "check_review": str(paths["check_review"]),
            "state_dir": workflow["state_dir"],
            "step_timeout": str(workflow["shell_timeout"]),
            "max_fix_iterations": str(workflow["max_fix_iterations"]),
            "max_srp_iterations": str(workflow["max_srp_iterations"]),
            "max_bug_iterations": str(workflow["max_bug_iterations"]),
            "max_comment_iterations": str(workflow["max_comment_iterations"]),
        },
    )
