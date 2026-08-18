"""Tests for the installed file layout and rendered script content."""

import os

from spec_utils import REPO_ROOT

from .installer_test_case import InstallerTestCase


class InstallLayoutTest(InstallerTestCase):
    """What the installer writes and its properties: the installed file
    layout, permissions and the rendered content of scripts and agents."""

    def test_install_creates_all_target_files(self):
        self.assertEqual(self.install(), 0)
        expected = [
            ".config/opencode/agent/planner.md",
            ".config/opencode/agent/executor.md",
            ".config/opencode/scripts/run-agent.sh",
            ".config/opencode/scripts/name-task.sh",
            ".config/opencode/scripts/planner-body.txt",
            ".config/opencode/scripts/executor-body.txt",
            # run-agent.sh is split one concern per file: the session store
            # and the cursor backend are sourced, prompt_subst.sh is called.
            ".config/opencode/scripts/session_store.sh",
            ".config/opencode/scripts/run-agent-cursor.sh",
            ".config/opencode/scripts/prompt_subst.sh",
            ".config/opencode/scripts/run-pipeline.py",
            # run-pipeline.py is split one class per file: the modules are
            # installed next to it so the wrapper stays importable.
            ".config/opencode/scripts/_run_pipeline_common.py",
            ".config/opencode/scripts/run_id_discoverer.py",
            ".config/opencode/scripts/step_result_poller.py",
            ".config/opencode/scripts/agent_log_tailer.py",
            ".config/opencode/scripts/gate_state.py",
            ".config/opencode/scripts/buffered_emitter.py",
            ".config/opencode/scripts/live_monitor.py",
            ".config/opencode/scripts/live_lines.py",
            ".config/opencode/scripts/config_invocation.py",
            ".config/opencode/scripts/run_statistics.py",
            ".config/opencode/scripts/latency_table.py",
            ".config/opencode/scripts/notify.py",
            ".config/opencode/scripts/feedback_editor.py",
            ".config/opencode/scripts/pty_spawn.py",
            ".config/opencode/scripts/editor.py",
            ".config/opencode/scripts/victory.wav",
            ".config/opencode/scripts/save_adr.py",
            ".config/opencode/scripts/check_review.py",
            ".config/opencode/scripts/check_implementation.py",
            ".config/opencode/scripts/check_questions.py",
            ".config/opencode/scripts/task_utils.py",
            ".config/opencode/scripts/adr_utils.py",
            ".config/opencode/scripts/agent_call.py",
            ".config/opencode/scripts/show-file.sh",
            ".config/spec-kit-llm-client/adr-pipeline.yml",
            ".config/spec-kit-llm-client/review-pipeline.yml",
            ".config/spec-kit-llm-client/task-pipeline.yml",
            ".config/spec-kit-llm-client/config.example.yml",
            ".config/spec-kit-llm-client/prompts/review/srp-review.md",
            ".config/spec-kit-llm-client/prompts/adr/implement.md",
            ".config/spec-kit-llm-client/prompts/task/study.md",
            ".config/spec-kit-llm-client/prompts/srp-fix.md",
            ".config/spec-kit-llm-client/install-path.txt",
            ".local/bin/spec-run",
            # spec-run's exceptions package (one class per file) and the
            # edit/editor modules copied next to the launcher.
            ".local/bin/exceptions/__init__.py",
            ".local/bin/exceptions/help_requested.py",
            ".local/bin/exceptions/invalid_invocation.py",
            ".local/bin/exceptions/edit_requested.py",
            ".local/bin/edit_command.py",
            ".local/bin/editor.py",
        ]
        for rel in expected:
            self.assertTrue((self.home / rel).exists(), rel)
        self.assertTrue(os.access(self.home / ".config/opencode/scripts/run-agent.sh", os.X_OK))
        self.assertTrue(os.access(self.home / ".config/opencode/scripts/name-task.sh", os.X_OK))
        self.assertTrue(
            os.access(self.home / ".config/opencode/scripts/prompt_subst.sh", os.X_OK)
        )
        self.assertTrue(os.access(self.home / ".local/bin/spec-run", os.X_OK))

    def test_reinstall_preserves_user_config(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            "# USER EDITED\n"
            "models:\n"
            "  planner:\n"
            "    provider: custom\n"
            "    model: my-model\n"
            "  executor:\n"
            "    provider: custom\n"
            "    model: exec-model\n"
            "workflow: {}\n"
        )
        self.assertEqual(self.install(), 0)
        self.assertIn("# USER EDITED", self.read_config())
        self.assertIn("my-model", self.read_config())

    def test_rendered_executor_has_model_and_permissions(self):
        self.assertEqual(self.install(), 0)
        executor = (self.home / ".config/opencode/agent/executor.md").read_text(encoding="utf-8")
        self.assertIn("opencode-go/deepseek-v4-flash", executor)
        self.assertIn("reasoningEffort: max", executor)
        self.assertIn("permission", executor)

    def test_rendered_planner_reasoning_from_config(self):
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace("reasoning: max", "reasoning: high", 1))
        self.assertEqual(self.install(), 0)
        planner = (self.home / ".config/opencode/agent/planner.md").read_text(encoding="utf-8")
        executor = (self.home / ".config/opencode/agent/executor.md").read_text(encoding="utf-8")
        self.assertIn("reasoningEffort: high", planner)
        self.assertIn("reasoningEffort: max", executor)

    def test_custom_state_dir_is_not_baked(self):
        # workflow.state_dir is configurable; the value must NOT be baked into
        # the installed scripts or workflows — it is delivered at runtime: the
        # wrapper reads the installed config.yml and passes state_dir to the
        # workflow as -i input, and run-agent.sh takes it from SKLC_STATE_DIR.
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("state_dir: .workflow", "state_dir: meta")
        )
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("meta", workflow)
        self.assertIn("{{ inputs.state_dir }}", workflow)
        parsed = self.parsed_workflow()
        self.assertEqual(parsed["inputs"]["state_dir"]["default"], ".workflow")
        run_agent = (self.home / ".config/opencode/scripts/run-agent.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("${SKLC_STATE_DIR:-.workflow}", run_agent)
        self.assertNotIn("meta", run_agent)
        wrapper = (self.home / ".config/opencode/scripts/run-pipeline.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("meta", wrapper)
        self.assertNotIn(".workflow/logs", wrapper)
        self.assertIn("SKLC_ATTACH_FLAG", wrapper)
        self.assertIn("SKLC_CONFIG", wrapper)

    def test_run_pipeline_wrapper_installed(self):
        self.assertEqual(self.install(), 0)
        wrapper = self.home / ".config/opencode/scripts/run-pipeline.py"
        self.assertTrue(wrapper.exists())
        self.assertTrue(os.access(wrapper, os.X_OK))
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("specify", text)
        self.assertIn("resume with: specify workflow resume", text)
        self.assertIn("LiveMonitor", text)
        self.assertIn("=== run statistics ===", text)
        self.assertIn("opencode", text)
        self.assertIn("export", text)
        # The wrapper resolves the victory.wav and the config from its own
        # location at runtime; no install-time values are baked in.
        self.assertIn("victory.wav", text)
        self.assertIn("SKLC_SCRIPTS_DIR", text)
        self.assertIn("SKLC_ATTACH_FLAG", text)
        self.assertNotIn(str(wrapper), text)
        self.assertNotIn("PYEOF", text)
        self.assertNotIn("#!/usr/bin/env bash", text)
        # The split modules are installed next to the wrapper: the poller
        # owns the state.json reads and the shared module the timestamp.
        poller = self.home / ".config/opencode/scripts/step_result_poller.py"
        self.assertIn("state.json", poller.read_text(encoding="utf-8"))
        common = self.home / ".config/opencode/scripts/_run_pipeline_common.py"
        self.assertIn('strftime("%H:%M:%S")', common.read_text(encoding="utf-8"))

    def test_spec_run_launcher_installed(self):
        self.assertEqual(self.install(), 0)
        launcher = self.home / ".local/bin/spec-run"
        self.assertTrue(launcher.exists())
        self.assertTrue(os.access(launcher, os.X_OK))
        text = launcher.read_text(encoding="utf-8")
        # Paths are derived from XDG_CONFIG_HOME/$HOME at runtime, not baked.
        self.assertIn("XDG_CONFIG_HOME", text)
        self.assertIn("install-path.txt", text)
        self.assertIn("os.execv", text)
        self.assertNotIn(str(self.home), text)
        # The installer records the repo's install.py path for `spec-run edit`.
        install_path = self.home / ".config/spec-kit-llm-client/install-path.txt"
        self.assertTrue(install_path.exists())
        self.assertEqual(
            install_path.read_text(encoding="utf-8").strip(), str(REPO_ROOT / "install.py")
        )

    def test_victory_wav_shipped_next_to_wrapper(self):
        self.assertEqual(self.install(), 0)
        wav = self.home / ".config/opencode/scripts/victory.wav"
        self.assertTrue(wav.is_file())
        shipped = REPO_ROOT / "architecture" / "assets" / "victory.wav"
        self.assertEqual(wav.read_bytes(), shipped.read_bytes())

    def test_run_agent_guards(self):
        self.assertEqual(self.install(), 0)
        run_agent = (self.home / ".config/opencode/scripts/run-agent.sh").read_text(
            encoding="utf-8"
        )
        session_store = (
            self.home / ".config/opencode/scripts/session_store.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--task)\n      [ $# -ge 2 ] || usage", run_agent)
        # --prompt-file is parsed in the same order-independent flag loop as
        # --task (the parallel fan-out calls `--review-fork <kind>
        # --prompt-file <path>`, ADR-0013).
        self.assertIn("--prompt-file)\n      [ $# -ge 2 ] || usage", run_agent)
        self.assertIn("--review-fork)", run_agent)
        # The stale-process cleanup lives in session_store.sh (one concern
        # per file): the pid file, the backend process-name pattern and the
        # kill are all owned there, shared by both backends.
        self.assertNotIn("ps -p", run_agent)
        self.assertIn("ps -p", session_store)
        self.assertIn("STALE_PROC_PATTERN", session_store)
        self.assertIn("^(cursor-agent|agent)$", session_store)
        self.assertIn("SKLC_BACKEND", run_agent)
        self.assertIn('> "$LOG_FILE" 2>&1', run_agent)
        self.assertNotIn('tail -c 4096 "$LOG_FILE"', run_agent)
        self.assertNotIn('cat "$LOG_FILE"', run_agent)
        self.assertIn("full log: $LOG_FILE", run_agent)
        self.assertNotIn('OUTPUT="$(opencode', run_agent)
        self.assertEqual(run_agent.count("session[_]?[iI][dD]"), 0)
        self.assertEqual(session_store.count("session[_]?[iI][dD]"), 1)
        self.assertNotIn("'name'", run_agent)

    def test_run_agent_cursor_dispatch_present(self):
        self.assertEqual(self.install(), 0)
        run_agent = (self.home / ".config/opencode/scripts/run-agent.sh").read_text(
            encoding="utf-8"
        )
        # The whole cursor backend lives in run-agent-cursor.sh, sourced by
        # run-agent.sh on demand: create-chat to mint a chat, --resume to
        # resume, --model from the role model env, --output-format json, and
        # the role body prefixed only on the first message of a fresh chat.
        cursor = (self.home / ".config/opencode/scripts/run-agent-cursor.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("run-agent-cursor.sh", run_agent)
        self.assertIn("session_store.sh", run_agent)
        self.assertIn("prompt_subst.sh", run_agent)
        self.assertIn('command -v cursor-agent', cursor)
        self.assertIn('create-chat', cursor)
        self.assertIn('--resume "$SESSION_ID"', cursor)
        self.assertIn('--model "$ROLE_MODEL"', cursor)
        self.assertIn('--output-format json', cursor)
        self.assertIn('ROLE_BODY_FILE', cursor)
        self.assertIn('PROMPT_FULL="$BODY', cursor)

    def test_cursor_only_install_writes_no_agent_files(self):
        # A cursor-only config (no opencode section) installs without opencode
        # agent files but still renders the role bodies next to run-agent.sh.
        self.write_config(
            "backend: cursor\n"
            "cursor:\n"
            "  models:\n"
            "    planner:\n"
            "      model: composer-2\n"
            "    executor:\n"
            "      model: composer-2\n"
            "workflow: {}\n"
        )
        self.assertEqual(self.install(), 0)
        self.assertFalse((self.home / ".config/opencode/agent/planner.md").exists())
        self.assertFalse((self.home / ".config/opencode/agent/executor.md").exists())
        planner_body = self.home / ".config/opencode/scripts/planner-body.txt"
        executor_body = self.home / ".config/opencode/scripts/executor-body.txt"
        self.assertTrue(planner_body.is_file())
        self.assertTrue(executor_body.is_file())
        self.assertIn("You are the planner", planner_body.read_text(encoding="utf-8"))
        self.assertIn("You are the executor", executor_body.read_text(encoding="utf-8"))

    def test_name_task_script_rendered(self):
        self.assertEqual(self.install(), 0)
        name_task = (self.home / ".config/opencode/scripts/name-task.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("kebab-case", name_task)
        self.assertIn("executor", name_task)
        self.assertIn("opencode run", name_task)
        # The cursor branch uses text output (final answer only, no parsing).
        self.assertIn("--output-format text", name_task)
        self.assertIn("SKLC_EXECUTOR_MODEL", name_task)
        self.assertNotIn("SESSION", name_task)

    def test_slug_sanitization_error_messages(self):
        self.assertEqual(self.install(), 0)
        adr_utils = (self.home / ".config/opencode/scripts/adr_utils.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("must contain ASCII letters", adr_utils)
        self.assertIn("w[:60]", adr_utils)

    def test_run_agent_sets_output_token_limit(self):
        # ADR-0007: opencode's default 32k per-response cap must be raised so
        # an agent cannot burn the whole budget on reasoning before acting.
        self.assertEqual(self.install(), 0)
        run_agent = (self.home / ".config/opencode/scripts/run-agent.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=1000000", run_agent)
        self.assertLess(
            run_agent.index("OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"),
            run_agent.index("--format json"),
        )
