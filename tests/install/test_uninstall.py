"""Tests for `modus-operandi uninstall` (via install.py --uninstall --home)."""

import io
from unittest import mock

from tests.env_sandbox import stdin, stdout

from .installer_test_case import InstallerTestCase


class UninstallTest(InstallerTestCase):
    """Uninstall removes everything modus-operandi owns (including the user's
    config.yml) and never removes anything when the confirmation prompt is
    declined."""

    def test_uninstall_removes_everything_with_yes(self) -> None:
        self.assertEqual(self.install(), 0)
        sink = io.StringIO()
        with stdout(sink):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertFalse((self.home / ".config/modus-operandi").exists())
        for rel in (
            ".config/opencode/agent/planner.md",
            ".config/opencode/agent/executor.md",
            ".config/opencode/agent/reviewer-srp.md",
            ".config/opencode/agent/reviewer-bugs.md",
            ".config/opencode/agent/reviewer-review.md",
            ".config/opencode/agent/reviewer-comment.md",
            ".config/opencode/scripts/run-agent.sh",
            ".config/opencode/scripts/name-task.sh",
            ".config/opencode/scripts/planner-body.txt",
            ".config/opencode/scripts/executor-body.txt",
            ".config/opencode/scripts/reviewer-srp-body.txt",
            ".config/opencode/scripts/reviewer-bugs-body.txt",
            ".config/opencode/scripts/reviewer-review-body.txt",
            ".config/opencode/scripts/reviewer-comment-body.txt",
            ".config/opencode/scripts/session_store.sh",
            ".config/opencode/scripts/run-agent-cursor.sh",
            ".config/opencode/scripts/prompt_subst.sh",
            ".config/opencode/scripts/run-pipeline.py",
            # run-pipeline.py is split one concern per file: the modules are
            # removed together with the wrapper.
            ".config/opencode/scripts/engine_output.py",
            ".config/opencode/scripts/feedback_gate.py",
            ".config/opencode/scripts/display.py",
            ".config/opencode/scripts/run_state.py",
            ".config/opencode/scripts/workflow_info.py",
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
            ".config/opencode/scripts/wrapper_cli.py",
            ".config/opencode/scripts/stdout_reader.py",
            ".config/opencode/scripts/run_finish.py",
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
        self.assertIn("pip uninstall modus-operandi", sink.getvalue())

    def test_uninstall_removes_step_scripts_and_legacy_bin(self) -> None:
        # The step scripts (one per shell step) and the legacy launcher
        # leftovers from the pre-pip model are cleaned up too.
        self.assertEqual(self.install(), 0)
        (self.home / ".local/bin").mkdir(parents=True, exist_ok=True)
        for name in ("modus-operandi", "editor.py", "edit_command.py"):
            (self.home / ".local/bin" / name).write_text("legacy", encoding="utf-8")
        (self.home / ".local/bin" / "exceptions").mkdir()
        rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        for rel in (
            ".config/opencode/scripts/agent-step.sh",
            ".config/opencode/scripts/review-check.sh",
            ".config/opencode/scripts/determine-scope.sh",
            ".config/opencode/scripts/review-task-id.sh",
            ".config/opencode/scripts/adr-task-id.sh",
            ".config/opencode/scripts/implement-retry.sh",
            ".config/opencode/scripts/clear-feedback.sh",
            ".config/opencode/scripts/implement-pass-check.sh",
            ".config/opencode/scripts/pass-check.sh",
            ".config/opencode/scripts/validate_inputs.py",
            ".config/opencode/scripts/check_plan_deviation.py",
            ".config/opencode/scripts/check_summary.py",
            ".local/bin/modus-operandi",
            ".local/bin/editor.py",
            ".local/bin/edit_command.py",
        ):
            self.assertFalse((self.home / rel).exists(), rel)
        self.assertFalse((self.home / ".local/bin/exceptions").exists())

    def test_uninstall_keeps_pip_owned_console_script(self) -> None:
        # `pip install --user modus-operandi` puts the console script into
        # ~/.local/bin and records it in the package RECORD; uninstall must
        # not delete it (pip uninstall removes it together with the wheel),
        # while legacy non-pip leftovers are still cleaned up.
        self.assertEqual(self.install(), 0)
        bin_dir = self.home / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        launcher = bin_dir / "modus-operandi"
        launcher.write_text("pip console script", encoding="utf-8")
        (bin_dir / "editor.py").write_text("legacy", encoding="utf-8")

        recorded = mock.Mock()
        recorded.locate.return_value = str(launcher)
        dist = mock.Mock()
        dist.files = [recorded]
        sink = io.StringIO()
        with (
            mock.patch(
                "modus_operandi.uninstall.importlib.metadata.distribution", return_value=dist
            ),
            stdout(sink),
        ):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertTrue(launcher.exists())
        self.assertFalse((bin_dir / "editor.py").exists())
        self.assertIn("kept the pip console scripts", sink.getvalue())
        self.assertIn("pip uninstall modus-operandi", sink.getvalue())

    def test_uninstall_keeps_pip_script_recorded_with_relative_path(self) -> None:
        # Real pip RECORD entries are stored relative to the dist-info dir
        # (e.g. ../../../bin/modus-operandi); locate() joins them WITHOUT
        # resolving the .. components, so the ownership check must normalize
        # both sides before comparing — otherwise the pip console script is
        # mistaken for a legacy leftover and deleted.
        self.assertEqual(self.install(), 0)
        bin_dir = self.home / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        launcher = bin_dir / "modus-operandi"
        launcher.write_text("pip console script", encoding="utf-8")

        recorded = mock.Mock()
        recorded.locate.return_value = str(
            self.home
            / ".local/lib/python3.12/site-packages/modus_operandi-0.1.0.dist-info"
            / "../../../../bin/modus-operandi"
        )
        dist = mock.Mock()
        dist.files = [recorded]
        sink = io.StringIO()
        with (
            mock.patch(
                "modus_operandi.uninstall.importlib.metadata.distribution", return_value=dist
            ),
            stdout(sink),
        ):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertTrue(launcher.exists())
        self.assertIn("kept the pip console scripts", sink.getvalue())

    def test_uninstall_removes_legacy_split_modules(self) -> None:
        # A machine upgraded from the released 0.1.0 package still has
        # scripts/_run_pipeline_common.py on disk (the pre-split module,
        # replaced by the five one-concern modules): uninstall must remove
        # it too, or "removes every modus-operandi-owned file" would be a
        # lie forever.
        self.assertEqual(self.install(), 0)
        legacy = self.home / ".config/opencode/scripts/_run_pipeline_common.py"
        legacy.write_text("legacy split module\n", encoding="utf-8")
        rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertFalse(legacy.exists())

    def test_uninstall_prompt_declined_removes_nothing(self) -> None:
        self.assertEqual(self.install(), 0)
        with stdin(io.StringIO("n\n")):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall"])
        self.assertEqual(rc, 1)
        self.assertTrue((self.home / ".config/modus-operandi/config.yml").exists())
        self.assertTrue((self.home / ".config/opencode/scripts/run-pipeline.py").exists())

    def test_uninstall_prompt_declined_on_eof(self) -> None:
        self.assertEqual(self.install(), 0)
        with stdin(io.StringIO("")):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall"])
        self.assertEqual(rc, 1)
        self.assertTrue((self.home / ".config/modus-operandi").exists())

    def test_uninstall_accepted_via_prompt(self) -> None:
        self.assertEqual(self.install(), 0)
        with stdin(io.StringIO("y\n")):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall"])
        self.assertEqual(rc, 0)
        self.assertFalse((self.home / ".config/modus-operandi").exists())
