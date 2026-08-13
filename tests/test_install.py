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

import install


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
        patcher = mock.patch.object(install, "run", side_effect=make_run(self.records))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, argv, which=which_fake):
        stderr = io.StringIO()
        with mock.patch.object(install, "find_in_path", side_effect=which):
            with mock.patch("sys.stderr", stderr):
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
        with mock.patch.object(Path, "home", return_value=self.home):
            with _chdir(Path(project.name)):
                self.assertEqual(self.run_main(["--register"])[0], 0)
                self.assertEqual(self.run_main(["--register"])[0], 0)
        adds = [
            cmd for cmd in self.records
            if cmd[1:3] == ["workflow", "add"]
        ]
        self.assertEqual(len(adds), 2)
        self.assertTrue(workflow.exists())

    def test_register_requires_project(self):
        self.assertEqual(self.install(), 0)
        project = tempfile.TemporaryDirectory()
        self.addCleanup(project.cleanup)
        with mock.patch.object(Path, "home", return_value=self.home):
            with _chdir(Path(project.name)):
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
        self.assertIn("verdict_input: final_verdict", workflow)
        self.assertIn('default: "approve"', workflow)

    def test_workflow_render_human_gates_true(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("verdict_input", workflow)

    def test_workflow_loop_and_final_verdict_structure(self):
        self.assertEqual(self.install(), 0)
        workflow = (
            self.home / ".config/spec-kit-llm-client/adr-pipeline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("do-while", workflow)
        self.assertIn('condition: "{{ steps.verdict.output.exit_code != 0 }}"', workflow)
        self.assertIn("continue_on_error: true", workflow)
        self.assertIn("sort -V", workflow)
        before_final_gate = workflow.split("final-gate", 1)[0]
        self.assertNotIn("continue_on_error", before_final_gate.split("final-verdict", 1)[1])

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
        self.assertIn("latest-review-{{ inputs.task_id }}.md", workflow)
        self.assertIn('show_file: ".workflow/tasks/latest-review-{{ inputs.task_id }}.md"', workflow)

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
                     "planner-answers", "implement", "review", "fix"):
            block = workflow.split("- id: %s" % step, 1)[1].split("\n  - id:", 1)[0]
            self.assertIn("timeout: 7200", block, step)
        self.assertNotIn("timeout", workflow.split("- id: verdict", 1)[1].split("- id: latest-review", 1)[0])

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

    def install_with_capture(self):
        return self.run_main(["--home", str(self.home)])


if __name__ == "__main__":
    unittest.main()
