"""Smoke tests for the spec-kit-llm-client installer.

Run with: python3 -m unittest tests.test_install  (from the repo root)
All installs go through --home <tempdir>; external commands are faked.
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spec_utils import InstallError, config, deps, verify
from spec_utils import cli as install


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def make_run(records=None):
    def _run(cmd, cwd=None, env=None, check=True):
        if records is not None:
            records.append(list(cmd))
        if cmd[-1] == "--version" and "specify" in cmd[0]:
            return FakeResult(0, "specify-cli 0.16.2\n")
        if cmd[1:3] == ["workflow", "run"]:
            return FakeResult(1, "", "Error: Required input 'feature' not provided.\n")
        if cmd[-3:] == ["opencode", "agent", "list"]:
            return FakeResult(0, "build (primary)\nplanner (subagent)\nexecutor (subagent)\n")
        if cmd[1:3] == ["workflow", "add"]:
            return FakeResult(0)
        return FakeResult(0)

    return _run


def which_fake(name):
    return {
        "opencode": "/usr/bin/opencode",
        "python3": "/usr/bin/python3",
        "specify": "/usr/bin/specify",
    }.get(name)


@contextlib.contextmanager
def _chdir(path):
    cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(cwd)


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.records = []
        patcher = mock.patch.object(deps, "run", side_effect=make_run(self.records))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, argv, which=which_fake):
        stderr = io.StringIO()
        with (
            mock.patch.object(deps, "find_in_path", side_effect=which),
            mock.patch("sys.stderr", stderr),
        ):
            rc = install.main(argv)
        return rc, stderr.getvalue()

    def install(self, *extra):
        return self.run_main(["--home", str(self.home), *extra])[0]

    def read_config(self):
        path = self.home / ".config" / "spec-kit-llm-client" / "config.yml"
        return path.read_text(encoding="utf-8")

    def write_config(self, text):
        path = self.home / ".config" / "spec-kit-llm-client" / "config.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_install_creates_all_target_files(self):
        self.assertEqual(self.install(), 0)
        expected = [
            ".config/opencode/agent/planner.md",
            ".config/opencode/agent/executor.md",
            ".config/opencode/scripts/run-agent.sh",
            ".config/opencode/scripts/save_adr.py",
            ".config/spec-kit-llm-client/config.yml",
            ".config/spec-kit-llm-client/config.example.yml",
            ".config/spec-kit-llm-client/adr-pipeline.yml",
        ]
        for rel in expected:
            self.assertTrue((self.home / rel).exists(), rel)
        self.assertTrue(
            os.access(self.home / ".config/opencode/scripts/run-agent.sh", os.X_OK)
        )

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

    def test_register_is_idempotent(self):
        self.assertEqual(self.install(), 0)
        workflow = self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        project = tempfile.TemporaryDirectory()
        self.addCleanup(project.cleanup)
        (Path(project.name) / ".specify").mkdir()
        with (
            mock.patch.object(Path, "home", return_value=self.home),
            _chdir(Path(project.name)),
        ):
            self.assertEqual(self.run_main(["--register"])[0], 0)
            self.assertEqual(self.run_main(["--register"])[0], 0)
        adds = [cmd for cmd in self.records if cmd[1:3] == ["workflow", "add"]]
        self.assertEqual(len(adds), 2)
        self.assertTrue(workflow.exists())

    def test_register_requires_project(self):
        self.assertEqual(self.install(), 0)
        project = tempfile.TemporaryDirectory()
        self.addCleanup(project.cleanup)
        with (
            mock.patch.object(Path, "home", return_value=self.home),
            _chdir(Path(project.name)),
        ):
            rc, err = self.run_main(["--register"])
        self.assertEqual(rc, 1)
        self.assertIn("specify init", err)

    def test_register_conflicts_with_home(self):
        rc, _ = self.run_main(["--home", str(self.home), "--register"])
        self.assertEqual(rc, 1)

    def test_missing_opencode_fails_with_message(self):
        def which(name):
            if name == "opencode":
                return None
            return which_fake(name)

        rc, err = self.run_main(["--home", str(self.home)], which=which)
        self.assertEqual(rc, 1)
        self.assertIn("opencode not found", err)

    def test_rendered_executor_has_model_and_permissions(self):
        self.assertEqual(self.install(), 0)
        executor = (
            self.home / ".config/opencode/agent/executor.md"
        ).read_text(encoding="utf-8")
        self.assertIn("opencode-go/deepseek-v4-flash", executor)
        self.assertIn("reasoningEffort: max", executor)
        self.assertIn("permission", executor)

    def test_rendered_planner_reasoning_from_config(self):
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace(
            "reasoning: max", "reasoning: high", 1
        ))
        self.assertEqual(self.install(), 0)
        planner = (
            self.home / ".config/opencode/agent/planner.md"
        ).read_text(encoding="utf-8")
        executor = (
            self.home / ".config/opencode/agent/executor.md"
        ).read_text(encoding="utf-8")
        self.assertIn("reasoningEffort: high", planner)
        self.assertIn("reasoningEffort: max", executor)

    def test_workflow_render_human_gates_false(self):
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace(
            "human_gates: true", "human_gates: false"
        ))
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("verdict_input: adr_verdict", workflow)
        self.assertIn('default: "approve"', workflow)
        self.assertNotIn("final_verdict", workflow)

    def test_workflow_render_human_gates_true(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("verdict_input", workflow)

    def test_workflow_loop_and_pass_check_structure(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("do-while", workflow)
        self.assertIn('condition: "{{ steps.verdict.output.exit_code != 0 }}"', workflow)
        self.assertIn("continue_on_error: true", workflow)
        self.assertIn("sort -V", workflow)
        self.assertIn("REVIEW OK: final verdict PASS", workflow)
        self.assertIn("WARNING: review loop exhausted", workflow)

    def test_workflow_task_id_is_required(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        block = workflow.split("task_id:", 1)[1].split("steps:", 1)[0]
        self.assertIn("required: true", block)
        self.assertNotIn("default:", block)

    def test_workflow_gates_show_files(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("show_file: \".workflow/tasks/{{ inputs.task_id }}/adr.md\"", workflow)
        self.assertNotIn("latest-review", workflow)
        self.assertNotIn("final-gate", workflow)
        self.assertNotIn("copy-latest-review", workflow)

    def test_workflow_saves_adr_to_adr_dir(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- id: save-adr", workflow)
        self.assertIn('save_adr.py" save', workflow)
        self.assertIn('"architecture"', workflow)
        self.assertIn("save_adr.py", workflow)
        self.assertNotIn("translit", workflow.lower().replace("transliteration", ""))
        self.assertNotIn("adr.md still has no 'slug' field", workflow)
        save_index = workflow.index("- id: save-adr")
        questions_index = workflow.index("- id: executor-questions")
        self.assertLess(save_index, questions_index)
        save_adr = (
            self.home / ".config/opencode/scripts/save_adr.py"
        ).read_text(encoding="utf-8")
        self.assertIn("read_slug", save_adr)
        self.assertIn("has no 'slug' field", save_adr)
        self.assertIn("must contain ASCII letters", save_adr)
        self.assertIn("w[:60]", save_adr)
        self.assertNotIn("translit", save_adr.lower().replace("transliteration", ""))

    def test_workflow_deviation_sync(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- id: sync-adr", workflow)
        self.assertIn("deviation.md", workflow)
        self.assertIn("## Amendments", workflow)
        block = workflow.split("- id: sync-adr", 1)[1].split("\n  - id:", 1)[0]
        self.assertIn("set -euo pipefail", block)
        self.assertIn('save_adr.py" sync', block)
        self.assertLess(block.index('save_adr.py" sync'), block.index("rm -f"))
        self.assertIn("timeout: 7200", block)
        save_adr = (
            self.home / ".config/opencode/scripts/save_adr.py"
        ).read_text(encoding="utf-8")
        self.assertIn("adr-saved.txt", save_adr)
        sync_index = workflow.index("- id: sync-adr")
        pass_index = workflow.index("- id: pass-check")
        review_loop_index = workflow.index("- id: review-loop")
        self.assertLess(review_loop_index, sync_index)
        self.assertLess(sync_index, pass_index)

    def test_workflow_approval_gate_after_loop(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- id: adr-unapproved", workflow)
        self.assertIn("- id: adr-approval-gate", workflow)
        self.assertIn("options: [approve, abort]", workflow)
        block = workflow.split("- id: adr-unapproved", 1)[1].split("\n  - id:", 1)[0]
        self.assertIn("{{ steps.adr-gate.output.choice != 'approve' }}", block)
        loop_index = workflow.index("- id: adr-loop")
        unapproved_index = workflow.index("- id: adr-unapproved")
        save_index = workflow.index("- id: save-adr")
        self.assertLess(loop_index, unapproved_index)
        self.assertLess(unapproved_index, save_index)

    def test_workflow_validate_task_id(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- id: validate-task-id", workflow)
        self.assertIn("'^[A-Za-z0-9_-]+$'", workflow)
        self.assertLess(workflow.index("validate-task-id"), workflow.index("write-adr"))
        run_agent = (
            self.home / ".config/opencode/scripts/run-agent.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("^[A-Za-z0-9_-]+$", run_agent)

    def test_run_agent_guards(self):
        self.assertEqual(self.install(), 0)
        run_agent = (
            self.home / ".config/opencode/scripts/run-agent.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--task) [ $# -ge 2 ] || usage", run_agent)
        self.assertIn("ps -p", run_agent)
        self.assertIn("grep -q '^opencode'", run_agent)
        self.assertEqual(run_agent.count("session[iI][dD]"), 1)

    def test_slug_sanitization_error_messages(self):
        self.assertEqual(self.install(), 0)
        save_adr = (
            self.home / ".config/opencode/scripts/save_adr.py"
        ).read_text(encoding="utf-8")
        self.assertIn("must contain ASCII letters", save_adr)
        self.assertIn("w[:60]", save_adr)

    def test_workflow_adr_revise_loop(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('options: [approve, revise, reject]', workflow)
        self.assertIn("adr-loop", workflow)
        self.assertIn("feedback.md", workflow)
        self.assertIn("{{ steps.adr-gate.output.choice != 'approve' }}", workflow)
        self.assertIn("adr-feedback-clear", workflow)

    def test_workflow_agent_steps_have_timeout(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        for step in ("write-adr", "adr-revise", "executor-questions",
                     "planner-answers", "implement", "review", "fix",
                     "sync-adr", "save-adr", "srp-review", "srp-fix"):
            block = workflow.split(f"- id: {step}", 1)[1].split("\n  - id:", 1)[0]
            self.assertIn("timeout: 7200", block, step)
        for step in ("verdict", "pass-check", "adr-feedback-clear",
                     "validate-task-id", "srp-verdict", "srp-pass-check"):
            block = workflow.split(f"- id: {step}", 1)[1]
            block = block.split("\n      - id:", 1)[0]
            block = block.split("\n  - id:", 1)[0]
            self.assertNotIn("timeout", block, step)

    def test_workflow_srp_loop_structure(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- id: srp-loop", workflow)
        self.assertIn("- id: srp-review", workflow)
        self.assertIn("- id: srp-verdict", workflow)
        self.assertIn("- id: srp-fix", workflow)
        self.assertIn("- id: srp-pass-check", workflow)
        self.assertIn("'^SRP: PASS'", workflow)
        self.assertIn("SRP REVIEW OK: final verdict PASS", workflow)
        self.assertIn("WARNING: SRP review loop exhausted", workflow)
        self.assertIn("{{ steps.srp-verdict.output.exit_code != 0 }}", workflow)
        block = workflow.split("- id: srp-loop", 1)[1].split("\n  - id:", 1)[0]
        self.assertIn("max_iterations: 5", block)
        self.assertIn("srp-review-*.md", block)
        self.assertIn("SRP: FIX", block)
        self.assertIn("- id: srp-fix-branch", block)
        implement_index = workflow.index("- id: implement")
        srp_index = workflow.index("- id: srp-loop")
        srp_check_index = workflow.index("- id: srp-pass-check")
        review_index = workflow.index("- id: review-loop")
        self.assertLess(implement_index, srp_index)
        self.assertLess(srp_check_index, review_index)

    def test_placeholder_config_is_rejected(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            "models:\n"
            "  planner:\n"
            "    provider: p\n"
            "    model: m\n"
            "  executor:\n"
            "    provider: <provider>\n"
            "    model: m\n"
            "workflow: {}\n"
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("placeholder", err)

    def test_malformed_config_reports_error_not_traceback(self):
        self.assertEqual(self.install(), 0)
        self.write_config("models: [\n")
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)

    def test_flag_conflicts_rejected(self):
        cases = [
            ["--uninstall", "--update"],
            ["--register", "--uninstall"],
            ["--register", "--update"],
        ]
        for extra in cases:
            rc, err = self.run_main(["--home", str(self.home), *extra])
            self.assertEqual(rc, 1, extra)
            self.assertIn("error:", err)

    def test_specify_candidates_finds_local_bin(self):
        (self.home / ".local" / "bin").mkdir(parents=True)
        (self.home / ".local" / "bin" / "specify").touch()
        with mock.patch.object(deps.Path, "home", return_value=self.home):
            self.assertIn(
                str(self.home / ".local/bin/specify"),
                deps._specify_candidates(),
            )

    def test_workflow_check_tolerates_stdout_message(self):
        def run_stdout(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(
                    1, "Error: Required input 'feature' not provided.\n", ""
                )
            return make_run()(cmd, cwd, env, check)

        with mock.patch.object(deps, "run", side_effect=run_stdout):
            self.assertEqual(self.install(), 0)

    def test_workflow_check_tolerates_lowercase_message(self):
        def run_lower(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(
                    1, "", "error: required input 'feature' not provided.\n"
                )
            return make_run()(cmd, cwd, env, check)

        with mock.patch.object(deps, "run", side_effect=run_lower):
            self.assertEqual(self.install(), 0)

    def test_uninstall_removes_files_keeps_config(self):
        self.assertEqual(self.install(), 0)
        rc, _ = self.run_main(["--home", str(self.home), "--uninstall", "--yes"])
        self.assertEqual(rc, 0)
        for rel in (
            ".config/opencode/agent/planner.md",
            ".config/opencode/agent/executor.md",
            ".config/opencode/scripts/run-agent.sh",
            ".config/opencode/scripts/save_adr.py",
            ".config/spec-kit-llm-client/adr-pipeline.yml",
            ".config/spec-kit-llm-client/config.example.yml",
        ):
            self.assertFalse((self.home / rel).exists(), rel)
        self.assertTrue(
            (self.home / ".config/spec-kit-llm-client/config.yml").exists()
        )

    def test_uninstall_prompts_declined_on_eof(self):
        self.assertEqual(self.install(), 0)
        with mock.patch("builtins.input", side_effect=EOFError):
            rc, _ = self.run_main(["--home", str(self.home), "--uninstall"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            [cmd for cmd in self.records if "uninstall" in cmd and cmd[0] != "uv"],
            [],
        )

    def test_verify_collects_all_errors(self):
        paths = config.build_paths(str(self.home))
        (self.home / ".config/opencode/agent").mkdir(parents=True)
        run_agent = self.home / ".config/opencode/scripts/run-agent.sh"
        run_agent.parent.mkdir(parents=True)
        run_agent.touch()
        run_agent.chmod(0o755)

        def run_fake(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(
                    1, "", "Error: Required input 'feature' not provided.\n"
                )
            if cmd[-3:] == ["opencode", "agent", "list"]:
                return FakeResult(0, "build (primary)\n")
            return FakeResult(0)

        with (
            mock.patch.object(deps, "run", side_effect=run_fake),
            self.assertRaises(InstallError) as cm,
        ):
            verify.verify_install(paths)
        err = str(cm.exception)
        self.assertIn("planner", err)
        self.assertIn("executor", err)
        self.assertIn("save_adr.py", err)

    def test_verify_workflow_syntax_specify_off_path(self):
        self.assertEqual(self.install(), 0)
        paths = config.build_paths(str(self.home))

        def which_off_specify(name):
            if name == "specify":
                return None
            return which_fake(name)

        with (
            mock.patch.object(
                deps, "find_in_path", side_effect=which_off_specify
            ),
            mock.patch.object(
                deps,
                "latest_specify_version",
                return_value=((0, 16), "/home/u/.local/bin/specify"),
            ),
            self.assertRaises(InstallError) as cm,
        ):
            verify.verify_install(paths)
        err = str(cm.exception)
        self.assertIn("'specify' not found on PATH", err)
        self.assertIn("/home/u/.local/bin/specify", err)

    def test_update_reports_new_options(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            "models:\n"
            "  planner:\n"
            "    provider: p\n"
            "    model: m\n"
            "  executor:\n"
            "    provider: p\n"
            "    model: m\n"
            "workflow: {}\n"
        )
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            rc = self.run_main(["--home", str(self.home), "--update"])[0]
        self.assertEqual(rc, 0)
        out = stdout.getvalue()
        self.assertIn("new options available", out)
        self.assertIn("workflow.max_srp_iterations", out)

    def install_with_capture(self):
        return self.run_main(["--home", str(self.home)])


if __name__ == "__main__":
    unittest.main()
