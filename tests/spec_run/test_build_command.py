"""Unit tests for build_command."""

import io
import tempfile
import unittest
from unittest import mock

from .helpers import load_spec_run


class BuildCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_spec_run(self.xdg)

    def test_adr_joins_feature_arguments(self):
        cmd = self.mod.build_command(["adr", "build a kanban board"])
        self.assertEqual(
            cmd,
            [self.mod.RUN_PIPELINE, self.mod.ADR_WORKFLOW, "-i", "feature=build a kanban board"],
        )

    def test_adr_joins_multiple_argv_elements_into_feature(self):
        cmd = self.mod.build_command(["adr", "build", "a", "kanban", "board"])
        self.assertEqual(cmd[-2:], ["-i", "feature=build a kanban board"])

    def test_adr_passthrough_inputs(self):
        cmd = self.mod.build_command(["adr", "feat", "-i", "task_id=my-feature"])
        self.assertEqual(
            cmd,
            [
                self.mod.RUN_PIPELINE,
                self.mod.ADR_WORKFLOW,
                "-i",
                "feature=feat",
                "-i",
                "task_id=my-feature",
            ],
        )

    def test_adr_combined_input_element(self):
        cmd = self.mod.build_command(["adr", "feat", "-i task_id=my-feature"])
        self.assertEqual(
            cmd,
            [
                self.mod.RUN_PIPELINE,
                self.mod.ADR_WORKFLOW,
                "-i",
                "feature=feat",
                "-i task_id=my-feature",
            ],
        )

    def test_adr_arg_starting_with_dash_i_stays_in_feature(self):
        # Regression: `startswith("-i")` used to swallow any feature argument
        # beginning with -i (e.g. -integration, -i18n) as a workflow input,
        # silently corrupting the feature. Only the exact `-i key=value` forms
        # are inputs; everything else joins the feature text.
        cmd = self.mod.build_command(["adr", "feat", "-i18n"])
        self.assertEqual(
            cmd,
            [self.mod.RUN_PIPELINE, self.mod.ADR_WORKFLOW, "-i", "feature=feat -i18n"],
        )
        self.assertNotIn("-i18n", cmd[3:])

    def test_adr_dangling_dash_i_is_invalid(self):
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["adr", "feat", "-i"])

    def test_backend_flag_prepends_to_adr(self):
        cmd = self.mod.build_command(["--backend", "cursor", "adr", "build a board"])
        self.assertEqual(
            cmd,
            [
                self.mod.RUN_PIPELINE,
                "--backend",
                "cursor",
                self.mod.ADR_WORKFLOW,
                "-i",
                "feature=build a board",
            ],
        )

    def test_backend_flag_prepends_to_review(self):
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

    def test_backend_flag_opencode_is_forwarded(self):
        cmd = self.mod.build_command(["--backend", "opencode", "review"])
        self.assertEqual(cmd[:3], [self.mod.RUN_PIPELINE, "--backend", "opencode"])

    def test_backend_flag_without_subcommand_is_invalid(self):
        for argv in (["--backend", "cursor"], ["--backend"]):
            with self.assertRaises(self.mod.InvalidInvocation):
                self.mod.build_command(argv)

    def test_backend_flag_invalid_value_is_invalid(self):
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["--backend", "bogus", "adr", "feat"])

    def test_backend_flag_help_still_prints_help(self):
        with self.assertRaises(self.mod.HelpRequested):
            self.mod.build_command(["--backend", "cursor", "--help"])

    def test_review_dangling_dash_i_is_invalid(self):
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["review", "-i"])

    def test_review_default(self):
        cmd = self.mod.build_command(["review"])
        self.assertEqual(cmd, [self.mod.RUN_PIPELINE, self.mod.REVIEW_WORKFLOW])

    def test_review_branch_diff(self):
        cmd = self.mod.build_command(["review", "--branch-diff"])
        self.assertEqual(
            cmd,
            [self.mod.RUN_PIPELINE, self.mod.REVIEW_WORKFLOW, "-i", "branch-diff=true"],
        )

    def test_review_passthrough_inputs(self):
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

    def test_no_literal_quotes_in_any_value(self):
        # Regression against the ADR's shell notation `-i feature="..."`: the
        # launcher passes values unquoted (no shell between it and specify),
        # or the workflow's validate-feature step would reject them.
        for argv in (["adr", "build a kanban board"], ["review", "--branch-diff"]):
            for arg in self.mod.build_command(argv):
                self.assertNotIn('"', arg)

    def test_edit_signals_edit_requested(self):
        # build_command only dispatches; the editor resolution happens in the
        # edit execution path (_run_edit), so `edit` maps to a signal, not to
        # an argv list.
        with self.assertRaises(self.mod.EditRequested):
            self.mod.build_command(["edit"])

    def test_edit_ignores_extra_arguments(self):
        # `edit` takes no arguments: extra argv elements must not change the
        # dispatch decision.
        with self.assertRaises(self.mod.EditRequested):
            self.mod.build_command(["edit", "--help", "stray"])

    def test_build_command_is_pure(self):
        # Mapping must never print: help/invalid are signalled by exceptions,
        # and the usage text lives in print_usage, so build_command writes to
        # neither stream for any outcome.
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch("sys.stdout", stdout),
            mock.patch("sys.stderr", stderr),
        ):
            self.mod.build_command(["adr", "feat"])
            self.mod.build_command(["review", "--branch-diff"])
            with self.assertRaises(self.mod.HelpRequested):
                self.mod.build_command(["--help"])
            with self.assertRaises(self.mod.InvalidInvocation):
                self.mod.build_command([])
            with self.assertRaises(self.mod.InvalidInvocation):
                self.mod.build_command(["frobnicate"])
            with self.assertRaises(self.mod.EditRequested):
                self.mod.build_command(["edit"])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_help_signals_help_requested(self):
        for argv in (["--help"], ["-h"]):
            with self.assertRaises(self.mod.HelpRequested):
                self.mod.build_command(argv)

    def test_no_args_is_invalid(self):
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command([])

    def test_unknown_subcommand_is_invalid(self):
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["frobnicate"])

    def test_adr_without_feature_is_invalid(self):
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["adr"])
