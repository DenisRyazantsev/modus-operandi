"""Tests for `spec-run uninstall` (via install.py --uninstall --home)."""

import io
from unittest import mock

from .installer_test_case import InstallerTestCase


class UninstallTest(InstallerTestCase):
    """Uninstall removes everything spec-run owns (including the user's
    config.yml) and never removes anything when the confirmation prompt is
    declined."""

    def test_uninstall_removes_everything_with_yes(self):
        self.assertEqual(self.install(), 0)
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertFalse((self.home / ".config/spec-run").exists())
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
            ".config/opencode/scripts/usage_parser.py",
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
        ):
            self.assertFalse((self.home / rel).exists(), rel)
        # The pip hint is printed.
        self.assertIn("pip uninstall spec-run", stdout.getvalue())

    def test_uninstall_removes_step_scripts_and_legacy_bin(self):
        # The step scripts (one per shell step) and the legacy launcher
        # leftovers from the pre-pip model are cleaned up too.
        self.assertEqual(self.install(), 0)
        (self.home / ".local/bin").mkdir(parents=True)
        for name in ("spec-run", "editor.py", "edit_command.py"):
            (self.home / ".local/bin" / name).write_text("legacy", encoding="utf-8")
        (self.home / ".local/bin" / "exceptions").mkdir()
        rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        for rel in (
            ".config/opencode/scripts/agent-step.sh",
            ".config/opencode/scripts/review-check.sh",
            ".config/opencode/scripts/warm-planner.sh",
            ".config/opencode/scripts/determine-scope.sh",
            ".config/opencode/scripts/review-task-id.sh",
            ".config/opencode/scripts/adr-task-id.sh",
            ".config/opencode/scripts/implement-retry.sh",
            ".config/opencode/scripts/sync-adr.sh",
            ".config/opencode/scripts/clear-feedback.sh",
            ".config/opencode/scripts/implement-pass-check.sh",
            ".config/opencode/scripts/pass-check.sh",
            ".config/opencode/scripts/validate_inputs.py",
            ".local/bin/spec-run",
            ".local/bin/editor.py",
            ".local/bin/edit_command.py",
        ):
            self.assertFalse((self.home / rel).exists(), rel)
        self.assertFalse((self.home / ".local/bin/exceptions").exists())

    def test_uninstall_keeps_pip_owned_console_script(self):
        # `pip install --user spec-run` puts the console script into
        # ~/.local/bin and records it in the package RECORD; uninstall must
        # not delete it (pip uninstall removes it together with the wheel),
        # while legacy non-pip leftovers are still cleaned up.
        self.assertEqual(self.install(), 0)
        bin_dir = self.home / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        launcher = bin_dir / "spec-run"
        launcher.write_text("pip console script", encoding="utf-8")
        (bin_dir / "editor.py").write_text("legacy", encoding="utf-8")

        recorded = mock.Mock()
        recorded.locate.return_value = str(launcher)
        dist = mock.Mock()
        dist.files = [recorded]
        stdout = io.StringIO()
        with (
            mock.patch(
                "spec_run.uninstall.importlib.metadata.distribution", return_value=dist
            ),
            mock.patch("sys.stdout", stdout),
        ):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertTrue(launcher.exists())
        self.assertFalse((bin_dir / "editor.py").exists())
        self.assertIn("kept the pip console scripts", stdout.getvalue())
        self.assertIn("pip uninstall spec-run", stdout.getvalue())

    def test_uninstall_prompt_declined_removes_nothing(self):
        self.assertEqual(self.install(), 0)
        with mock.patch("builtins.input", return_value="n"):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall"])
        self.assertEqual(rc, 1)
        self.assertTrue((self.home / ".config/spec-run/config.yml").exists())
        self.assertTrue((self.home / ".config/opencode/scripts/run-pipeline.py").exists())

    def test_uninstall_prompt_declined_on_eof(self):
        self.assertEqual(self.install(), 0)
        with mock.patch("builtins.input", side_effect=EOFError):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall"])
        self.assertEqual(rc, 1)
        self.assertTrue((self.home / ".config/spec-run").exists())

    def test_uninstall_accepted_via_prompt(self):
        self.assertEqual(self.install(), 0)
        with mock.patch("builtins.input", return_value="y"):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall"])
        self.assertEqual(rc, 0)
        self.assertFalse((self.home / ".config/spec-run").exists())
