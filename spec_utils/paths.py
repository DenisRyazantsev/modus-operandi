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
        "prompts": base / ".config" / "spec-kit-llm-client" / "prompts",
        "run_agent": base / ".config" / "opencode" / "scripts" / "run-agent.sh",
        "name_task": base / ".config" / "opencode" / "scripts" / "name-task.sh",
        # run-agent.sh is split one concern per file: the session store and
        # the cursor backend are sourced, prompt_subst.sh is called.
        "session_store": base / ".config" / "opencode" / "scripts" / "session_store.sh",
        "run_agent_cursor": (
            base / ".config" / "opencode" / "scripts" / "run-agent-cursor.sh"
        ),
        "prompt_subst": base / ".config" / "opencode" / "scripts" / "prompt_subst.sh",
        # Role bodies as plain text, read by run-agent.sh for the cursor
        # backend (cursor has no agent files to carry the role).
        "planner_body": base / ".config" / "opencode" / "scripts" / "planner-body.txt",
        "executor_body": base / ".config" / "opencode" / "scripts" / "executor-body.txt",
        "run_pipeline": base / ".config" / "opencode" / "scripts" / "run-pipeline.py",
        # run-pipeline.py is split one class per file; the modules below are
        # copied next to it so the installed wrapper stays importable.
        "run_pipeline_common": (
            base / ".config" / "opencode" / "scripts" / "_run_pipeline_common.py"
        ),
        "run_id_discoverer": base / ".config" / "opencode" / "scripts" / "run_id_discoverer.py",
        "step_result_poller": base / ".config" / "opencode" / "scripts" / "step_result_poller.py",
        "agent_log_tailer": base / ".config" / "opencode" / "scripts" / "agent_log_tailer.py",
        "gate_state": base / ".config" / "opencode" / "scripts" / "gate_state.py",
        "buffered_emitter": base / ".config" / "opencode" / "scripts" / "buffered_emitter.py",
        "live_monitor": base / ".config" / "opencode" / "scripts" / "live_monitor.py",
        # run-pipeline.py is further split one concern per file: the
        # config-to-invocation mapping, the statistics, the victory sound,
        # the feedback gate's editor interaction and the pty plumbing.
        "config_invocation": (
            base / ".config" / "opencode" / "scripts" / "config_invocation.py"
        ),
        "run_statistics": (
            base / ".config" / "opencode" / "scripts" / "run_statistics.py"
        ),
        "notify": base / ".config" / "opencode" / "scripts" / "notify.py",
        "feedback_editor": (
            base / ".config" / "opencode" / "scripts" / "feedback_editor.py"
        ),
        "pty_spawn": base / ".config" / "opencode" / "scripts" / "pty_spawn.py",
        # The shared editor resolution is copied next to both consumers: the
        # scripts/ copy for the feedback gate, the bin copy for the launcher.
        "editor": base / ".config" / "opencode" / "scripts" / "editor.py",
        "launcher_editor": base / ".local" / "bin" / "editor.py",
        "victory_wav": base / ".config" / "opencode" / "scripts" / "victory.wav",
        "save_adr": base / ".config" / "opencode" / "scripts" / "save_adr.py",
        "check_review": base / ".config" / "opencode" / "scripts" / "check_review.py",
        "check_implementation": (
            base / ".config" / "opencode" / "scripts" / "check_implementation.py"
        ),
        "task_utils": base / ".config" / "opencode" / "scripts" / "task_utils.py",
        "adr_utils": base / ".config" / "opencode" / "scripts" / "adr_utils.py",
        "agent_call": base / ".config" / "opencode" / "scripts" / "agent_call.py",
        # spec-run is split one class per file: the exceptions package, the
        # edit command and the shared editor module are copied next to the
        # launcher so it stays importable.
        "exceptions_dir": base / ".local" / "bin" / "exceptions",
        "edit_command": base / ".local" / "bin" / "edit_command.py",
    }
