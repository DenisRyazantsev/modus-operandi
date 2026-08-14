"""Rendering: install templates into the target home directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from string import Template
from typing import Any

from . import TEMPLATES_DIR, Paths


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
    use_serve = cfg["workflow"]["use_serve"]
    serve_attach = "--attach http://localhost:4096" if use_serve else ""
    render_file(
        TEMPLATES_DIR / "run-agent.sh.tpl",
        paths["run_agent"],
        {"serve_attach": serve_attach},
    )
    paths["run_agent"].chmod(0o755)


def render_save_adr(paths: Paths) -> None:
    shutil.copy2(TEMPLATES_DIR / "save_adr.py", paths["save_adr"])


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
        approve_verdict = "    verdict_input: adr_verdict"
    render_file(
        TEMPLATES_DIR / "adr-pipeline.yml.tpl",
        paths["workflow"],
        {
            "run_agent": str(paths["run_agent"]),
            "save_adr": str(paths["save_adr"]),
            "state_dir": workflow["state_dir"],
            "adr_dir": workflow["adr_dir"],
            "step_timeout": str(workflow["shell_timeout"]),
            "verdict_inputs_decl": verdict_decl,
            "approve_adr_verdict": approve_verdict,
            "max_fix_iterations": str(workflow["max_fix_iterations"]),
            "max_srp_iterations": str(workflow["max_srp_iterations"]),
            "max_bug_iterations": str(workflow["max_bug_iterations"]),
            "max_comment_iterations": str(workflow["max_comment_iterations"]),
        },
    )


def render_review_workflow(cfg: dict[str, Any], paths: Paths) -> None:
    # The review-only workflow has no inputs and no ADR stage: it diffs the
    # working tree against the default branch and runs the same review loops.
    workflow = cfg["workflow"]
    render_file(
        TEMPLATES_DIR / "review-pipeline.yml.tpl",
        paths["review_workflow"],
        {
            "run_agent": str(paths["run_agent"]),
            "save_adr": str(paths["save_adr"]),
            "state_dir": workflow["state_dir"],
            "step_timeout": str(workflow["shell_timeout"]),
            "max_fix_iterations": str(workflow["max_fix_iterations"]),
            "max_srp_iterations": str(workflow["max_srp_iterations"]),
            "max_bug_iterations": str(workflow["max_bug_iterations"]),
            "max_comment_iterations": str(workflow["max_comment_iterations"]),
        },
    )
