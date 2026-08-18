"""Tests for --uninstall."""

from unittest import mock

from .installer_test_case import InstallerTestCase


class UninstallTest(InstallerTestCase):
    """--uninstall removes the installed files but keeps the user config, and
    never removes anything when the confirmation prompt is declined."""

    def test_uninstall_removes_files_keeps_config(self):
        self.assertEqual(self.install(), 0)
        rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        for rel in (
            ".config/opencode/agent/planner.md",
            ".config/opencode/agent/executor.md",
            ".config/opencode/scripts/run-agent.sh",
            ".config/opencode/scripts/name-task.sh",
            ".config/opencode/scripts/planner-body.txt",
            ".config/opencode/scripts/executor-body.txt",
            ".config/opencode/scripts/session_store.sh",
            ".config/opencode/scripts/run-agent-cursor.sh",
            ".config/opencode/scripts/prompt_subst.sh",
            ".config/opencode/scripts/run-pipeline.py",
            # run-pipeline.py is split one class per file: the modules are
            # removed together with the wrapper.
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
            ".config/spec-kit-llm-client/install-path.txt",
            ".local/bin/spec-run",
            # The exceptions package and the edit/editor modules ship next to
            # the launcher.
            ".local/bin/exceptions",
            ".local/bin/edit_command.py",
            ".local/bin/editor.py",
        ):
            self.assertFalse((self.home / rel).exists(), rel)
        self.assertTrue((self.home / ".config/spec-kit-llm-client/config.yml").exists())

    def test_uninstall_prompts_declined_on_eof(self):
        self.assertEqual(self.install(), 0)
        with mock.patch("builtins.input", side_effect=EOFError):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            [cmd for cmd in self.records if "uninstall" in cmd and cmd[0] != "uv"],
            [],
        )
