"""Unit tests for build_command."""

import io
import tempfile
import unittest

from tests.env_sandbox import stderr, stdout

from .helpers import load_modus_operandi


class BuildCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_modus_operandi(self.xdg)

    def test_task_joins_arguments(self) -> None:
        cmd = self.mod.build_command(["task", "add a dark mode toggle"])
        self.assertEqual(
            cmd,
            [self.mod.RUN_PIPELINE, self.mod.TASK_WORKFLOW, "-i", "task=add a dark mode toggle"],
        )

    def test_task_joins_multiple_argv_elements_into_task(self) -> None:
        cmd = self.mod.build_command(["task", "add", "a", "dark", "mode", "toggle"])
        self.assertEqual(cmd[-2:], ["-i", "task=add a dark mode toggle"])

    def test_task_passthrough_inputs(self) -> None:
        cmd = self.mod.build_command(["task", "feat", "-i", "task_id=my-task"])
        self.assertEqual(
            cmd,
            [
                self.mod.RUN_PIPELINE,
                self.mod.TASK_WORKFLOW,
                "-i",
                "task=feat",
                "-i",
                "task_id=my-task",
            ],
        )

    def test_task_combined_input_element(self) -> None:
        cmd = self.mod.build_command(["task", "feat", "-i task_id=my-task"])
        self.assertEqual(
            cmd,
            [
                self.mod.RUN_PIPELINE,
                self.mod.TASK_WORKFLOW,
                "-i",
                "task=feat",
                "-i task_id=my-task",
            ],
        )

    def test_task_arg_starting_with_dash_i_stays_in_task(self) -> None:
        cmd = self.mod.build_command(["task", "feat", "-i18n"])
        self.assertEqual(
            cmd,
            [self.mod.RUN_PIPELINE, self.mod.TASK_WORKFLOW, "-i", "task=feat -i18n"],
        )
        self.assertNotIn("-i18n", cmd[3:])

    def test_task_dangling_dash_i_is_invalid(self) -> None:
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["task", "feat", "-i"])

    def test_task_without_task_is_invalid(self) -> None:
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["task"])

    def test_backend_flag_prepends_to_task(self) -> None:
        cmd = self.mod.build_command(["--backend", "cursor", "task", "add a toggle"])
        self.assertEqual(
            cmd,
            [
                self.mod.RUN_PIPELINE,
                "--backend",
                "cursor",
                self.mod.TASK_WORKFLOW,
                "-i",
                "task=add a toggle",
            ],
        )

    def test_backend_flag_prepends_to_review(self) -> None:
        cmd = self.mod.build_command(["--backend", "cursor", "review", "--branch-diff"])
        self.assertEqual(
            cmd,
            [
                self.mod.RUN_PIPELINE,
                "--backend",
                "cursor",
                self.mod.REVIEW_WORKFLOW,
                "-i",
                "branch-diff=true",
            ],
        )

    def test_backend_flag_opencode_is_forwarded(self) -> None:
        cmd = self.mod.build_command(["--backend", "opencode", "review"])
        self.assertEqual(cmd[:3], [self.mod.RUN_PIPELINE, "--backend", "opencode"])

    def test_backend_flag_without_subcommand_is_invalid(self) -> None:
        for argv in (["--backend", "cursor"], ["--backend"]):
            with self.assertRaises(self.mod.InvalidInvocation):
                self.mod.build_command(argv)

    def test_backend_flag_invalid_value_is_invalid(self) -> None:
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["--backend", "bogus", "task", "feat"])

    def test_backend_flag_help_still_prints_help(self) -> None:
        with self.assertRaises(self.mod.HelpRequested):
            self.mod.build_command(["--backend", "cursor", "--help"])

    def test_review_dangling_dash_i_is_invalid(self) -> None:
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["review", "-i"])

    def test_review_default(self) -> None:
        cmd = self.mod.build_command(["review"])
        self.assertEqual(cmd, [self.mod.RUN_PIPELINE, self.mod.REVIEW_WORKFLOW])

    def test_review_branch_diff(self) -> None:
        cmd = self.mod.build_command(["review", "--branch-diff"])
        self.assertEqual(
            cmd,
            [self.mod.RUN_PIPELINE, self.mod.REVIEW_WORKFLOW, "-i", "branch-diff=true"],
        )

    def test_review_passthrough_inputs(self) -> None:
        cmd = self.mod.build_command(["review", "--branch-diff", "-i", "task_id=x"])
        self.assertEqual(
            cmd,
            [
                self.mod.RUN_PIPELINE,
                self.mod.REVIEW_WORKFLOW,
                "-i",
                "branch-diff=true",
                "-i",
                "task_id=x",
            ],
        )

    def test_no_literal_quotes_in_any_value(self) -> None:
        # Regression against the ADR's shell notation `-i task="..."`: the
        # launcher passes values unquoted (no shell between it and specify),
        # or the workflow's validate-task step would reject them.
        for argv in (["task", "add a dark mode toggle"], ["review", "--branch-diff"]):
            for arg in self.mod.build_command(argv):
                self.assertNotIn('"', arg)

    def test_edit_signals_edit_requested(self) -> None:
        # build_command only dispatches; the editor resolution happens in the
        # edit execution path (_run_edit), so `edit` maps to a signal, not to
        # an argv list.
        with self.assertRaises(self.mod.EditRequested):
            self.mod.build_command(["edit"])

    def test_edit_ignores_extra_arguments(self) -> None:
        # `edit` takes no arguments: extra argv elements must not change the
        # dispatch decision.
        with self.assertRaises(self.mod.EditRequested):
            self.mod.build_command(["edit", "--help", "stray"])

    def test_uninstall_signals_uninstall_requested(self) -> None:
        with self.assertRaises(self.mod.UninstallRequested) as cm:
            self.mod.build_command(["uninstall"])
        self.assertFalse(cm.exception.yes)

    def test_uninstall_yes_flag(self) -> None:
        with self.assertRaises(self.mod.UninstallRequested) as cm:
            self.mod.build_command(["uninstall", "--yes"])
        self.assertTrue(cm.exception.yes)

    def test_uninstall_yes_anywhere_after_subcommand(self) -> None:
        with self.assertRaises(self.mod.UninstallRequested) as cm:
            self.mod.build_command(["uninstall", "stray", "--yes"])
        self.assertTrue(cm.exception.yes)

    def test_build_command_is_pure(self) -> None:
        # Mapping must never print: help/invalid are signalled by exceptions,
        # and the usage text lives in print_usage, so build_command writes to
        # neither stream for any outcome.
        with stdout(io.StringIO()) as out, stderr(io.StringIO()) as err:
            self.mod.build_command(["task", "feat"])
            self.mod.build_command(["review", "--branch-diff"])
            with self.assertRaises(self.mod.HelpRequested):
                self.mod.build_command(["--help"])
            with self.assertRaises(self.mod.InvalidInvocation):
                self.mod.build_command([])
            with self.assertRaises(self.mod.InvalidInvocation):
                self.mod.build_command(["frobnicate"])
            with self.assertRaises(self.mod.EditRequested):
                self.mod.build_command(["edit"])
            with self.assertRaises(self.mod.UninstallRequested):
                self.mod.build_command(["uninstall"])
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "")

    def test_help_signals_help_requested(self) -> None:
        for argv in (["--help"], ["-h"]):
            with self.assertRaises(self.mod.HelpRequested):
                self.mod.build_command(argv)

    def test_no_args_is_invalid(self) -> None:
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command([])

    def test_unknown_subcommand_is_invalid(self) -> None:
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["frobnicate"])
