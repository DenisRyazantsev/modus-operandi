"""Install layout: where each generated file lives under a config base.

Two entry points share one layout: ``build_paths(home)`` derives the config
base as ``<home>/.config`` (the dev flow and the installer tests, which pass
``--home``), and ``build_paths_from_config_base(base)`` takes an existing
config base directly (the launcher, which resolves XDG_CONFIG_HOME at
runtime). ``user_bin`` (``<base-parent>/.local/bin``) holds the dev-flow
launcher (written by install.py) and the legacy launcher leftovers that
``modus-operandi uninstall`` cleans up; the pip console script lives there
too when installed with ``pip install --user``.
"""

from __future__ import annotations

from pathlib import Path

Paths = dict[str, Path]


def _layout(base: Path) -> Paths:
    return {
        "agents": base / "opencode" / "agent",
        "scripts": base / "opencode" / "scripts",
        "config_dir": base / "modus-operandi",
        "config": base / "modus-operandi" / "config.yml",
        "config_example": base / "modus-operandi" / "config.example.yml",
        "install_version": base / "modus-operandi" / "install-version.txt",
        "review_workflow": base / "modus-operandi" / "review-pipeline.yml",
        "task_workflow": base / "modus-operandi" / "task-pipeline.yml",
        "prompts": base / "modus-operandi" / "prompts",
        "user_bin": base.parent / ".local" / "bin",
        # run-agent.sh is split one concern per file: the session store and
        # the cursor backend are sourced, prompt_subst.sh is called.
        "run_agent": base / "opencode" / "scripts" / "run-agent.sh",
        "name_task": base / "opencode" / "scripts" / "name-task.sh",
        "session_store": base / "opencode" / "scripts" / "session_store.sh",
        "run_agent_cursor": (base / "opencode" / "scripts" / "run-agent-cursor.sh"),
        "prompt_subst": base / "opencode" / "scripts" / "prompt_subst.sh",
        # Role bodies as plain text, read by run-agent.sh for the cursor
        # backend (cursor has no agent files to carry the role).
        "planner_body": base / "opencode" / "scripts" / "planner-body.txt",
        "executor_body": base / "opencode" / "scripts" / "executor-body.txt",
        "run_pipeline": base / "opencode" / "scripts" / "run-pipeline.py",
        # run-pipeline.py is split one concern per file; the modules below
        # are copied next to it so the installed wrapper stays importable.
        "engine_output": base / "opencode" / "scripts" / "engine_output.py",
        "feedback_gate": base / "opencode" / "scripts" / "feedback_gate.py",
        "display": base / "opencode" / "scripts" / "display.py",
        "run_state": base / "opencode" / "scripts" / "run_state.py",
        "workflow_info": base / "opencode" / "scripts" / "workflow_info.py",
        "run_id_discoverer": base / "opencode" / "scripts" / "run_id_discoverer.py",
        "step_result_poller": base / "opencode" / "scripts" / "step_result_poller.py",
        "agent_log_tailer": base / "opencode" / "scripts" / "agent_log_tailer.py",
        "gate_state": base / "opencode" / "scripts" / "gate_state.py",
        "buffered_emitter": base / "opencode" / "scripts" / "buffered_emitter.py",
        "live_monitor": base / "opencode" / "scripts" / "live_monitor.py",
        "live_lines": base / "opencode" / "scripts" / "live_lines.py",
        # The aligned column layout of the log rows (ADR-0016).
        "table_format": base / "opencode" / "scripts" / "table_format.py",
        # The agent-log usage schema (opencode step_finish, cursor usage
        # shapes) is a separate concern used by both the live lines and the
        # run statistics: copied next to them so the installed modules stay
        # importable (SRP split).
        "usage_parser": base / "opencode" / "scripts" / "usage_parser.py",
        # run-pipeline.py is further split one concern per file: the
        # config-to-invocation mapping, the statistics, the victory sound,
        # the feedback gate's editor interaction, the pty plumbing, the
        # CLI surface, the engine-stdout consumption policy and the run
        # teardown/outcome reporting.
        "config_invocation": (base / "opencode" / "scripts" / "config_invocation.py"),
        "run_statistics": (base / "opencode" / "scripts" / "run_statistics.py"),
        "latency_table": (base / "opencode" / "scripts" / "latency_table.py"),
        "notify": base / "opencode" / "scripts" / "notify.py",
        "feedback_editor": (base / "opencode" / "scripts" / "feedback_editor.py"),
        "pty_spawn": base / "opencode" / "scripts" / "pty_spawn.py",
        "wrapper_cli": base / "opencode" / "scripts" / "wrapper_cli.py",
        "stdout_reader": base / "opencode" / "scripts" / "stdout_reader.py",
        "run_finish": base / "opencode" / "scripts" / "run_finish.py",
        # The shared editor resolution, copied next to the run-pipeline
        # wrapper for its feedback gates.
        "editor": base / "opencode" / "scripts" / "editor.py",
        "victory_wav": base / "opencode" / "scripts" / "victory.wav",
        "save_adr": base / "opencode" / "scripts" / "save_adr.py",
        "check_review": base / "opencode" / "scripts" / "check_review.py",
        "check_implementation": (base / "opencode" / "scripts" / "check_implementation.py"),
        "check_questions": base / "opencode" / "scripts" / "check_questions.py",
        "check_plan_deviation": (base / "opencode" / "scripts" / "check_plan_deviation.py"),
        "task_utils": base / "opencode" / "scripts" / "task_utils.py",
        "adr_utils": base / "opencode" / "scripts" / "adr_utils.py",
        "agent_call": base / "opencode" / "scripts" / "agent_call.py",
        # Workflow step scripts (CONTRIBUTING.md: the workflows call exactly
        # one installed script per shell step - no bash in YAML). Copied
        # verbatim like every other pipeline script.
        "agent_step": base / "opencode" / "scripts" / "agent-step.sh",
        "review_check": base / "opencode" / "scripts" / "review-check.sh",
        "warm_planner": base / "opencode" / "scripts" / "warm-planner.sh",
        "determine_scope": base / "opencode" / "scripts" / "determine-scope.sh",
        "review_task_id": base / "opencode" / "scripts" / "review-task-id.sh",
        "adr_task_id": base / "opencode" / "scripts" / "adr-task-id.sh",
        "implement_retry": base / "opencode" / "scripts" / "implement-retry.sh",
        "clear_feedback": base / "opencode" / "scripts" / "clear-feedback.sh",
        "implement_pass_check": (base / "opencode" / "scripts" / "implement-pass-check.sh"),
        "pass_check": base / "opencode" / "scripts" / "pass-check.sh",
        "show_file": base / "opencode" / "scripts" / "show-file.sh",
        "validate_inputs": base / "opencode" / "scripts" / "validate_inputs.py",
    }


def build_paths(home: str | Path) -> Paths:
    """The install layout for a home directory (dev flow, ``--home``)."""
    return _layout(Path(home) / ".config")


def build_paths_from_config_base(config_base: str | Path) -> Paths:
    """The install layout for a config base (runtime: XDG_CONFIG_HOME or
    ``~/.config``)."""
    return _layout(Path(config_base))
