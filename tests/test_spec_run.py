"""Unit tests for the static spec-run launcher (pipeline_scripts/spec_run.py).

The launcher derives every installed path from XDG_CONFIG_HOME/$HOME at import
time and reads the repo's install.py path from install-path.txt at edit time;
the tests point XDG_CONFIG_HOME at a temp dir and write the metadata file
there, exercising both the path derivation and the argument-mapping behavior.
"""

import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = REPO_ROOT / "pipeline_scripts" / "spec_run.py"

INSTALL_PY = "/home/user/spec-kit-llm-client/install.py"


def load_spec_run(config_base: str) -> types.ModuleType:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config_base}, clear=True):
        spec = importlib.util.spec_from_file_location("spec_run_under_test", _SRC)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["spec_run_under_test"] = module
        spec.loader.exec_module(module)
    return module


class LauncherPathsTest(unittest.TestCase):
    def test_paths_derived_from_config_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = load_spec_run(tmp)
            base = Path(tmp)
            self.assertEqual(
                mod.RUN_PIPELINE, str(base / "opencode" / "scripts" / "run-pipeline.py")
            )
            self.assertEqual(
                mod.ADR_WORKFLOW,
                str(base / "spec-kit-llm-client" / "adr-pipeline.yml"),
            )
            self.assertEqual(
                mod.REVIEW_WORKFLOW,
                str(base / "spec-kit-llm-client" / "review-pipeline.yml"),
            )
            self.assertEqual(
                mod.CONFIG, str(base / "spec-kit-llm-client" / "config.yml")
            )
            self.assertEqual(
                mod.INSTALL_PATH_FILE,
                base / "spec-kit-llm-client" / "install-path.txt",
            )


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


class EditorResolutionTest(unittest.TestCase):
    """The launcher's editor resolution chain: $VISUAL -> $EDITOR -> nano ->
    vi, each candidate validated on PATH, with malformed values skipped."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_spec_run(self.xdg)

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


class PrintUsageTest(unittest.TestCase):
    def _load(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return load_spec_run(self.tmp.name)

    def test_print_usage_defaults_to_stdout(self):
        mod = self._load()
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            mod.print_usage()
        self.assertIn("Usage:", captured.getvalue())

    def test_print_usage_writes_to_given_stream(self):
        mod = self._load()
        err = io.StringIO()
        mod.print_usage(err)
        self.assertIn("Usage:", err.getvalue())


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = self.tmp.name
        self.mod = load_spec_run(self.xdg)

    def _record_install_py(self):
        config_dir = Path(self.xdg) / "spec-kit-llm-client"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "install-path.txt").write_text(INSTALL_PY, encoding="utf-8")

    def test_main_execs_run_pipeline(self):
        mod = self.mod
        with mock.patch.object(mod.os, "execv") as execv:
            mod.main(["adr", "build a kanban board"])
        execv.assert_called_once()
        self.assertEqual(
            execv.call_args.args[1],
            [mod.RUN_PIPELINE, mod.ADR_WORKFLOW, "-i", "feature=build a kanban board"],
        )

    def test_main_help_exit_zero(self):
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            rc = self.mod.main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("Usage:", captured.getvalue())

    def test_main_no_args_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = self.mod.main([])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_unknown_subcommand_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = self.mod.main(["frobnicate"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_adr_without_feature_exit_nonzero(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            rc = self.mod.main(["adr"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", err.getvalue())

    def test_main_dangling_input_exit_nonzero(self):
        for argv in (["adr", "feat", "-i"], ["review", "-i"]):
            with self.subTest(argv=argv), mock.patch("sys.stderr", io.StringIO()) as err:
                rc = self.mod.main(argv)
            self.assertEqual(rc, 1)
            self.assertIn("Usage:", err.getvalue())

    def test_main_execv_failure_reports_error(self):
        mod = self.mod
        with (
            mock.patch.object(mod.os, "execv", side_effect=OSError("no such file")),
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["review"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())

    def test_main_edit_runs_editor_then_installer(self):
        mod = self.mod
        self._record_install_py()
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
        self.assertEqual(
            calls, [["nano", mod.CONFIG], [sys.executable, INSTALL_PY, "--apply"]]
        )

    def test_main_edit_propagates_installer_exit_code(self):
        mod = self.mod
        self._record_install_py()
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
        mod = self.mod
        self._record_install_py()
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
        self.assertEqual(
            calls, [["nano", mod.CONFIG], [sys.executable, INSTALL_PY, "--apply"]]
        )

    def test_main_edit_editor_start_failure_returns_nonzero(self):
        mod = self.mod
        self._record_install_py()

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

    def test_main_edit_without_recorded_install_py_fails_cleanly(self):
        # The repo clone was moved/deleted: install-path.txt is missing and
        # `edit` must fail with a readable error, not a traceback.
        mod = self.mod
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(mod.shutil, "which", return_value="/usr/bin/nano"),
            mock.patch("subprocess.run") as run,
            mock.patch("sys.stderr", io.StringIO()) as err,
        ):
            rc = mod.main(["edit"])
        self.assertEqual(rc, 1)
        run.assert_called_once()  # only the editor launch, no --apply
        self.assertIn("install.py", err.getvalue())
        self.assertIn("install-path.txt", err.getvalue())


if __name__ == "__main__":
    unittest.main()
