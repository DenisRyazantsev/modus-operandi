"""Unit tests for the rendered spec-run launcher template.

spec_run.py.tpl is a string.Template; the tests render it with test paths and
load the result as a module, exercising both the placeholder substitution and
the argument-mapping behavior.
"""

import importlib.util
import io
import string
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = (REPO_ROOT / "templates" / "spec_run.py.tpl").read_text(encoding="utf-8")

RUN_PIPELINE = "/home/user/.config/opencode/scripts/run-pipeline.py"
ADR_WORKFLOW = "/home/user/.config/spec-kit-llm-client/adr-pipeline.yml"
REVIEW_WORKFLOW = "/home/user/.config/spec-kit-llm-client/review-pipeline.yml"
CONFIG = "/home/user/.config/spec-kit-llm-client/config.yml"
INSTALL_PY = "/home/user/spec-kit-llm-client/install.py"


def load_spec_run() -> types.ModuleType:
    rendered = string.Template(_TEMPLATE).substitute(
        run_pipeline=RUN_PIPELINE,
        adr_workflow=ADR_WORKFLOW,
        review_workflow=REVIEW_WORKFLOW,
        config=CONFIG,
        install_py=INSTALL_PY,
    )
    tmpdir = Path(tempfile.mkdtemp(prefix="spec_run_test_"))
    path = tmpdir / "spec_run.py"
    path.write_text(rendered, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("spec_run_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["spec_run_under_test"] = module
    spec.loader.exec_module(module)
    return module


class BuildCommandTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_spec_run()

    def test_adr_joins_feature_arguments(self):
        cmd = self.mod.build_command(["adr", "build a kanban board"])
        self.assertEqual(
            cmd,
            [RUN_PIPELINE, ADR_WORKFLOW, "-i", "feature=build a kanban board"],
        )

    def test_adr_joins_multiple_argv_elements_into_feature(self):
        cmd = self.mod.build_command(["adr", "build", "a", "kanban", "board"])
        self.assertEqual(cmd[-2:], ["-i", "feature=build a kanban board"])

    def test_adr_passthrough_inputs(self):
        cmd = self.mod.build_command(["adr", "feat", "-i", "task_id=my-feature"])
        self.assertEqual(
            cmd,
            [RUN_PIPELINE, ADR_WORKFLOW, "-i", "feature=feat", "-i", "task_id=my-feature"],
        )

    def test_adr_combined_input_element(self):
        cmd = self.mod.build_command(["adr", "feat", "-i task_id=my-feature"])
        self.assertEqual(
            cmd,
            [RUN_PIPELINE, ADR_WORKFLOW, "-i", "feature=feat", "-i task_id=my-feature"],
        )

    def test_adr_arg_starting_with_dash_i_stays_in_feature(self):
        # Regression: `startswith("-i")` used to swallow any feature argument
        # beginning with -i (e.g. -integration, -i18n) as a workflow input,
        # silently corrupting the feature. Only the exact `-i key=value` forms
        # are inputs; everything else joins the feature text.
        cmd = self.mod.build_command(["adr", "feat", "-i18n"])
        self.assertEqual(cmd, [RUN_PIPELINE, ADR_WORKFLOW, "-i", "feature=feat -i18n"])
        self.assertNotIn("-i18n", cmd[3:])

    def test_adr_dangling_dash_i_is_invalid(self):
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["adr", "feat", "-i"])

    def test_review_dangling_dash_i_is_invalid(self):
        with self.assertRaises(self.mod.InvalidInvocation):
            self.mod.build_command(["review", "-i"])

    def test_review_default(self):
        cmd = self.mod.build_command(["review"])
        self.assertEqual(cmd, [RUN_PIPELINE, REVIEW_WORKFLOW])

    def test_review_branch_diff(self):
        cmd = self.mod.build_command(["review", "--branch-diff"])
        self.assertEqual(cmd, [RUN_PIPELINE, REVIEW_WORKFLOW, "-i", "branch-diff=true"])

    def test_review_passthrough_inputs(self):
        cmd = self.mod.build_command(["review", "--branch-diff", "-i", "task_id=x"])
        self.assertEqual(
            cmd,
            [RUN_PIPELINE, REVIEW_WORKFLOW, "-i", "branch-diff=true", "-i", "task_id=x"],
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

    def test_editor_prefers_visual_over_editor(self):
        with mock.patch.dict(
            "os.environ",
            {"VISUAL": "code --wait", "EDITOR": "vim"},
            clear=True,
        ):
            self.assertEqual(self.mod._resolve_editor(), ["code", "--wait"])

    def test_editor_uses_editor_when_visual_unset(self):
        with mock.patch.dict("os.environ", {"EDITOR": "emacs -nw"}, clear=True):
            self.assertEqual(self.mod._resolve_editor(), ["emacs", "-nw"])

    def test_editor_falls_back_to_nano_then_vi(self):
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(self.mod.shutil, "which", side_effect=lambda name: None),
        ):
            self.assertEqual(self.mod._resolve_editor(), ["vi"])
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(
                self.mod.shutil, "which", side_effect=lambda name: "/usr/bin/" + name
            ),
        ):
            self.assertEqual(self.mod._resolve_editor(), ["nano"])

    def test_editor_malformed_visual_falls_back_to_editor(self):
        with (
            mock.patch.dict(
                "os.environ", {"VISUAL": 'code --wait"', "EDITOR": "vim"}, clear=True
            ),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            self.assertEqual(self.mod._resolve_editor(), ["vim"])
        self.assertIn("malformed", err.getvalue())

    def test_editor_malformed_value_falls_back_to_default(self):
        # An unbalanced quote makes shlex.split raise ValueError; the value is
        # skipped (with a warning) instead of crashing with a traceback.
        with (
            mock.patch.dict("os.environ", {"EDITOR": "emacs '"}, clear=True),
            mock.patch.object(self.mod.shutil, "which", return_value="/usr/bin/nano"),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            self.assertEqual(self.mod._resolve_editor(), ["nano"])
        self.assertIn("malformed", err.getvalue())

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


class PrintUsageTest(unittest.TestCase):
    def test_print_usage_defaults_to_stdout(self):
        mod = load_spec_run()
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            mod.print_usage()
        self.assertIn("Usage:", captured.getvalue())

    def test_print_usage_writes_to_given_stream(self):
        mod = load_spec_run()
        err = io.StringIO()
        mod.print_usage(err)
        self.assertIn("Usage:", err.getvalue())


class MainTest(unittest.TestCase):
    def test_main_execs_run_pipeline(self):
        mod = load_spec_run()
        with mock.patch.object(mod.os, "execv") as execv:
            mod.main(["adr", "build a kanban board"])
        execv.assert_called_once()
        self.assertEqual(
            execv.call_args.args[1],
            [RUN_PIPELINE, ADR_WORKFLOW, "-i", "feature=build a kanban board"],
        )

    def test_main_help_exit_zero(self):
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            rc = load_spec_run().main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("Usage:", captured.getvalue())

    def test_main_no_args_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = load_spec_run().main([])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_unknown_subcommand_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = load_spec_run().main(["frobnicate"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_adr_without_feature_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = load_spec_run().main(["adr"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_dangling_input_exit_nonzero(self):
        for argv in (["adr", "feat", "-i"], ["review", "-i"]):
            with self.subTest(argv=argv), mock.patch("sys.stderr", io.StringIO()) as err:
                rc = load_spec_run().main(argv)
            self.assertEqual(rc, 1)
            self.assertIn("Usage:", err.getvalue())

    def test_main_execv_failure_reports_error(self):
        mod = load_spec_run()
        with (
            mock.patch.object(mod.os, "execv", side_effect=OSError("no such file")),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["review"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())

    def test_main_edit_runs_editor_then_installer(self):
        mod = load_spec_run()
        calls: list[list[str]] = []

        def fake_run(cmd, check=True):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0)

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(mod.shutil, "which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["nano", CONFIG], [sys.executable, INSTALL_PY, "--apply"]])

    def test_main_edit_propagates_installer_exit_code(self):
        mod = load_spec_run()
        results = iter(
            [types.SimpleNamespace(returncode=0), types.SimpleNamespace(returncode=3)]
        )

        def fake_run(cmd, check=True):
            return next(results)

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(mod.shutil, "which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 3)

    def test_main_edit_applies_after_nonzero_editor_exit(self):
        # A user can save a valid edit and still close the editor non-zero
        # (vim :cq, ...); the config must still be re-applied then.
        mod = load_spec_run()
        calls: list[list[str]] = []
        results = iter(
            [types.SimpleNamespace(returncode=7), types.SimpleNamespace(returncode=0)]
        )

        def fake_run(cmd, check=True):
            calls.append(cmd)
            return next(results)

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(mod.shutil, "which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["nano", CONFIG], [sys.executable, INSTALL_PY, "--apply"]])

    def test_main_edit_editor_start_failure_returns_nonzero(self):
        mod = load_spec_run()

        def fake_run(cmd, check=True):
            if cmd[0] == "nano":
                raise OSError("no such file")
            return types.SimpleNamespace(returncode=0)

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(mod.shutil, "which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
