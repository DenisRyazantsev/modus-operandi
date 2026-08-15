"""Install layout: where each generated file lives under a home directory."""

from __future__ import annotations

from pathlib import Path

Paths = dict[str, Path]


def build_paths(home: str | Path) -> Paths:
    base = Path(home)
    return {
        "agents": base / ".config" / "opencode" / "agent",
        "scripts": base / ".config" / "opencode" / "scripts",
        "config_dir": base / ".config" / "spec-kit-llm-client",
        "config": base / ".config" / "spec-kit-llm-client" / "config.yml",
        "config_example": base / ".config" / "spec-kit-llm-client" / "config.example.yml",
        "install_path": base / ".config" / "spec-kit-llm-client" / "install-path.txt",
        "user_bin": base / ".local" / "bin",
        "spec_run": base / ".local" / "bin" / "spec-run",
        "workflow": base / ".config" / "spec-kit-llm-client" / "adr-pipeline.yml",
        "review_workflow": base / ".config" / "spec-kit-llm-client" / "review-pipeline.yml",
        "run_agent": base / ".config" / "opencode" / "scripts" / "run-agent.sh",
        "name_task": base / ".config" / "opencode" / "scripts" / "name-task.sh",
        "run_pipeline": base / ".config" / "opencode" / "scripts" / "run-pipeline.py",
        "victory_wav": base / ".config" / "opencode" / "scripts" / "victory.wav",
        "save_adr": base / ".config" / "opencode" / "scripts" / "save_adr.py",
        "check_review": base / ".config" / "opencode" / "scripts" / "check_review.py",
        "check_implementation": (
            base / ".config" / "opencode" / "scripts" / "check_implementation.py"
        ),
        "task_utils": base / ".config" / "opencode" / "scripts" / "task_utils.py",
        "adr_utils": base / ".config" / "opencode" / "scripts" / "adr_utils.py",
        "agent_call": base / ".config" / "opencode" / "scripts" / "agent_call.py",
    }
