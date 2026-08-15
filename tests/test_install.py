"""Smoke tests for the spec-kit-llm-client installer.

Run with: python3 -m unittest tests.test_install  (from the repo root)
All installs go through --home <tempdir>; external commands are faked.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spec_utils import (
    REPO_ROOT,
    InstallError,
    paths,
    proc,
    tool_discovery,
    verify,
    versions,
    yaml_loader,
)
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
        return FakeResult(0)

    return _run


def which_fake(name):
    return {
        "opencode": "/usr/bin/opencode",
        "python3": "/usr/bin/python3",
        "specify": "/usr/bin/specify",
    }.get(name)


class InstallerTestCase(unittest.TestCase):
    """Shared fixture for every install test: a fresh --home temp dir and a
    faked external-command layer, plus the helpers the focused test classes
    use to drive the installer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.records = []
        patcher = mock.patch.object(proc, "run", side_effect=make_run(self.records))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def parsed_workflow(self, rel=".config/spec-kit-llm-client/adr-pipeline.yml"):
        return yaml_loader.yaml.safe_load(
            (self.home / rel).read_text(encoding="utf-8")
        )

    def find_step(self, steps, step_id):
        """Recursively find a step by id in the parsed workflow steps."""
        for step in steps:
            if step.get("id") == step_id:
                return step
            for branch in ("steps", "then", "else"):
                nested = step.get(branch)
                if isinstance(nested, list):
                    found = self.find_step(nested, step_id)
                    if found is not None:
                        return found
        return None

    def run_main(self, argv, which=which_fake):
        stderr = io.StringIO()
        with (
            mock.patch.object(tool_discovery, "find_in_path", side_effect=which),
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
            ".config/opencode/scripts/run-pipeline.py",
            ".config/opencode/scripts/victory.wav",
            ".config/opencode/scripts/save_adr.py",
            ".config/opencode/scripts/check_review.py",
            ".config/opencode/scripts/check_implementation.py",
            ".config/opencode/scripts/task_utils.py",
            ".config/opencode/scripts/adr_utils.py",
            ".config/opencode/scripts/agent_call.py",
            ".config/spec-kit-llm-client/adr-pipeline.yml",
            ".config/spec-kit-llm-client/config.example.yml",
            ".config/spec-kit-llm-client/adr-pipeline.yml",
            ".config/spec-kit-llm-client/install-path.txt",
            ".local/bin/spec-run",
        ]
        for rel in expected:
            self.assertTrue((self.home / rel).exists(), rel)
        self.assertTrue(os.access(self.home / ".config/opencode/scripts/run-agent.sh", os.X_OK))
        self.assertTrue(os.access(self.home / ".config/opencode/scripts/name-task.sh", os.X_OK))
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
        self.assertIn("state.json", text)
        self.assertIn("resume with: specify workflow resume", text)
        self.assertIn("LiveMonitor", text)
        self.assertIn('strftime("%H:%M:%S")', text)
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
        self.assertIn("--task) [ $# -ge 2 ] || usage", run_agent)
        self.assertIn("ps -p", run_agent)
        self.assertIn("grep -q '^opencode'", run_agent)
        self.assertIn('> "$LOG_FILE" 2>&1', run_agent)
        self.assertNotIn('tail -c 4096 "$LOG_FILE"', run_agent)
        self.assertNotIn('cat "$LOG_FILE"', run_agent)
        self.assertIn("full log: $LOG_FILE", run_agent)
        self.assertNotIn('OUTPUT="$(opencode', run_agent)
        self.assertEqual(run_agent.count("session[iI][dD]"), 1)
        self.assertNotIn("'name'", run_agent)

    def test_name_task_script_rendered(self):
        self.assertEqual(self.install(), 0)
        name_task = (self.home / ".config/opencode/scripts/name-task.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("kebab-case", name_task)
        self.assertIn("executor", name_task)
        self.assertIn("opencode run", name_task)
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


class PrerequisitesTest(InstallerTestCase):
    """Install-time prerequisite checks: missing tools, the specify workflow
    syntax check tolerating message variations, and specify discovery."""

    def test_missing_opencode_fails_with_message(self):
        def which(name):
            if name == "opencode":
                return None
            return which_fake(name)

        rc, err = self.run_main(["--home", str(self.home)], which=which)
        self.assertEqual(rc, 1)
        self.assertIn("opencode not found", err)

    def test_workflow_check_tolerates_stdout_message(self):
        def run_stdout(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(1, "Error: Required input 'feature' not provided.\n", "")
            return make_run()(cmd, cwd, env, check)

        with mock.patch.object(proc, "run", side_effect=run_stdout):
            self.assertEqual(self.install(), 0)

    def test_workflow_check_tolerates_lowercase_message(self):
        def run_lower(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(1, "", "error: required input 'feature' not provided.\n")
            return make_run()(cmd, cwd, env, check)

        with mock.patch.object(proc, "run", side_effect=run_lower):
            self.assertEqual(self.install(), 0)

    def test_specify_candidates_finds_local_bin(self):
        (self.home / ".local" / "bin").mkdir(parents=True)
        (self.home / ".local" / "bin" / "specify").touch()
        with mock.patch.object(versions.Path, "home", return_value=self.home):
            self.assertIn(
                str(self.home / ".local/bin/specify"),
                versions._specify_candidates(),
            )


class ConfigValidationTest(InstallerTestCase):
    """The installed config.yml is validated: malformed, placeholder and
    wrongly-typed values are rejected with a clean error, never a traceback."""

    def install_with_capture(self):
        return self.run_main(["--home", str(self.home)])

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

    def test_non_mapping_config_root_reports_error_not_traceback(self):
        # A config.yml that is valid YAML but whose top level is not a mapping
        # (a bare scalar or a list) must fail with a clean InstallError, not
        # an unhandled TypeError traceback from dict(raw).
        for content in ("42\n", "- a\n- b\n"):
            with self.subTest(content=content):
                # Restore a valid config first: install() must not proceed
                # over the previous subTest's broken config.
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
                self.assertEqual(self.install(), 0)
                self.write_config(content)
                rc, err = self.install_with_capture()
                self.assertEqual(rc, 1)
                self.assertIn("top-level must be a mapping", err)
                self.assertNotIn("Traceback", err)

    def test_boolean_iteration_values_rejected(self):
        # bool is a subclass of int: `max_fix_iterations: true` used to pass
        # the integer check and render as "max_iterations: True".
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_fix_iterations: 5", "max_fix_iterations: true")
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("max_fix_iterations must be an integer", err)

    def test_boolean_shell_timeout_rejected(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("shell_timeout: 7200", "shell_timeout: true")
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("shell_timeout must be a positive number", err)

    def test_null_state_dir_rejected(self):
        # str(None) is "None", which used to pass the regex and point every
        # workflow step at "None/tasks/...".
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace("state_dir: .workflow", "state_dir: null"))
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("workflow.state_dir must be a string", err)

    def test_non_string_adr_dir_rejected(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("adr_dir: architecture", "adr_dir: 42")
        )
        rc, err = self.install_with_capture()
        self.assertEqual(rc, 1)
        self.assertIn("workflow.adr_dir must be a string", err)


class WorkflowStructureTest(InstallerTestCase):
    """The installed adr-pipeline.yml and review-pipeline.yml structures:
    step ids, ordering, inputs, loops, gate options and inline shell blocks."""

    def shell_runs(self, steps):
        for step in steps:
            if step.get("type") == "shell" and isinstance(step.get("run"), str):
                yield step["id"], step["run"]
            for branch in ("steps", "then", "else"):
                nested = step.get(branch)
                if isinstance(nested, list):
                    yield from self.shell_runs(nested)

    def test_workflow_gate_verdict_input_always_present(self):
        # The ADR gate's verdict is delivered at runtime: the workflow always
        # declares the adr_verdict input (default "approve") and binds it on
        # the gate, and the run-pipeline.py wrapper passes an empty adr_verdict
        # (interactive) or omits it (auto-approve) per human_gates.
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("verdict_input: adr_verdict", workflow)
        self.assertIn("default: approve", workflow)
        self.assertNotIn("final_verdict", workflow)
        parsed = self.parsed_workflow()
        self.assertIsNotNone(parsed)
        adr_loop = next(s for s in parsed["steps"] if s["id"] == "adr-loop")
        adr_gate = next(s for s in adr_loop["steps"] if s["id"] == "adr-gate")
        self.assertEqual(adr_gate["verdict_input"], "adr_verdict")
        self.assertEqual(parsed["inputs"]["adr_verdict"]["default"], "approve")
        self.assertEqual(
            parsed["inputs"]["adr_verdict"]["enum"],
            ["", "approve", "revise", "reject"],
        )

    def test_workflow_input_defaults_stay_at_config_defaults(self):
        # state_dir/adr_dir are NOT baked: they are declared as optional
        # workflow inputs with the config default values, and the launcher
        # passes the configured values via -i at runtime.
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow()
        self.assertEqual(parsed["inputs"]["state_dir"]["default"], ".workflow")
        self.assertEqual(parsed["inputs"]["adr_dir"]["default"], "architecture")
        self.assertFalse(parsed["inputs"]["state_dir"].get("required"))
        self.assertFalse(parsed["inputs"]["adr_dir"].get("required"))

    def test_workflow_scripts_dir_has_fallback_for_direct_runs(self):
        # `specify workflow run <path> -i feature=...` is a documented entry
        # point that does not go through run-pipeline.py: SKLC_SCRIPTS_DIR is
        # then unset, so every step referencing the scripts must fall back to
        # the default install location instead of expanding to "/run-agent.sh".
        self.assertEqual(self.install(), 0)
        fallback = 'SKLC_SCRIPTS_DIR="${SKLC_SCRIPTS_DIR:-$HOME/.config/opencode/scripts}"'

        def missing_fallback(steps, missing):
            for step in steps:
                run = step.get("run")
                if isinstance(run, str) and "$SKLC_SCRIPTS_DIR" in run and fallback not in run:
                    missing.append(step.get("id"))
                for branch in ("steps", "then", "else"):
                    nested = step.get(branch)
                    if isinstance(nested, list):
                        missing_fallback(nested, missing)

        for rel in (
            ".config/spec-kit-llm-client/adr-pipeline.yml",
            ".config/spec-kit-llm-client/review-pipeline.yml",
        ):
            parsed = self.parsed_workflow(rel)
            missing: list = []
            missing_fallback(parsed["steps"], missing)
            self.assertEqual(missing, [], rel)

    def test_workflow_loop_and_pass_check_structure(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("do-while", workflow)
        self.assertIn("{{ steps.verdict.output.exit_code != 0 }}", workflow)
        self.assertIn("continue_on_error: true", workflow)
        self.assertIn("check_review.py", workflow)
        self.assertIn('check_review.py" check-review', workflow)
        verdict_run = self.find_step(self.parsed_workflow()["steps"], "verdict")["run"]
        self.assertIn(
            'check-review "{{ inputs.state_dir }}" "{{ inputs.task_id }}" review',
            verdict_run,
        )
        pass_check_run = self.find_step(self.parsed_workflow()["steps"], "pass-check")["run"]
        self.assertIn("REVIEW OK: final verdict PASS", pass_check_run)
        self.assertIn("WARNING: review loop exhausted", pass_check_run)
        self.assertIn("- id: fix-branch", workflow)
        self.assertNotIn("sort -V", workflow)

    def test_workflow_task_id_is_optional(self):
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow()
        task_id = parsed["inputs"]["task_id"]
        self.assertEqual(task_id["required"], False)
        self.assertNotIn("default", task_id)

    def test_workflow_generate_task_id_structure(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: generate-task-id", workflow)
        block = workflow.split("- id: generate-task-id", 1)[1].split("- id: write-adr", 1)[0]
        self.assertIn("name-task.sh", block)
        self.assertNotIn('run-agent.sh" name', block)
        self.assertIn("date +%Y%m%d-%H%M", block)
        self.assertIn("ln -sfn", block)
        self.assertIn("tasks/current", block)
        validate_index = workflow.index("- id: validate-task-id")
        generate_index = workflow.index("- id: generate-task-id")
        write_index = workflow.index("- id: write-adr")
        self.assertLess(validate_index, generate_index)
        self.assertLess(generate_index, write_index)

    def test_workflow_gates_show_files(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("{{ inputs.state_dir }}/tasks/current/adr.md", workflow)
        self.assertNotIn("latest-review", workflow)
        self.assertNotIn("final-gate", workflow)
        self.assertNotIn("copy-latest-review", workflow)

    def test_review_workflow_structure(self):
        self.assertEqual(self.install(), 0)
        review = (self.home / ".config/spec-kit-llm-client/review-pipeline.yml").read_text(
            encoding="utf-8"
        )
        parsed = self.parsed_workflow(".config/spec-kit-llm-client/review-pipeline.yml")
        runs: list[str] = []

        def collect(steps):
            for step in steps:
                run = step.get("run")
                if isinstance(run, str):
                    runs.append(run)
                for branch in ("steps", "then", "else"):
                    nested = step.get(branch)
                    if isinstance(nested, list):
                        collect(nested)

        collect(parsed["steps"])
        all_runs = " ".join(runs)
        self.assertIn("id: review-pipeline", review)
        self.assertNotIn("inputs: {}", review)
        self.assertIn("branch-diff:", review)
        for step in (
            "generate-task-id",
            "determine-scope",
            "srp-loop",
            "bug-loop",
            "review-loop",
            "comment-review-loop",
            "report",
        ):
            self.assertIn(f"- id: {step}", review, step)
        for kind in ("srp", "bugs", "review", "comment"):
            self.assertIn(f'check-review "{{{{ inputs.state_dir }}}}" "" {kind}', all_runs, kind)
        self.assertIn("scope.txt", all_runs)
        self.assertIn("refs/remotes/origin/HEAD", all_runs)
        self.assertIn("origin/main", all_runs)
        self.assertIn("origin/master", all_runs)
        self.assertIn("no changes against", all_runs)
        # `git diff --quiet` ignores untracked files, so a branch containing
        # only NEW files must not be rejected as "nothing to review".
        self.assertIn("git ls-files --others --exclude-standard", all_runs)
        self.assertIn("branch-diff: ", all_runs)
        self.assertIn("mode: full codebase review", all_runs)
        self.assertIn("git branch --show-current", all_runs)
        self.assertIn("date +%Y%m%d-%H%M", all_runs)
        self.assertIn("ln -sfn", all_runs)
        self.assertIn("review-report.md", all_runs)
        self.assertNotIn("base=$(cat", all_runs)
        self.assertNotIn("adr.md", all_runs)
        self.assertNotIn("adr_dir", all_runs)
        self.assertNotIn("--task", all_runs)

    def test_review_rerun_prompts_include_git_status(self):
        # Regression: git diff <snapshot> never shows untracked files, so a
        # NEW file the executor creates while fixing a finding was invisible
        # in every subsequent re-review. Each re-review prompt must also ask
        # for git status so untracked files are in the review scope.
        self.assertEqual(self.install(), 0)
        review = (self.home / ".config/spec-kit-llm-client/review-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("git diff $snap and git status", review)
        self.assertIn("does not show untracked files", review)

    def test_review_first_iteration_prompts_include_untracked_files(self):
        # Regression: determine-scope admits branches whose only changes are
        # untracked files, but the first-iteration prompts told the reviewer
        # to look only at `git diff <base>` — which is empty for untracked
        # files. Every first-iteration prompt must also ask for git status so
        # untracked files are in the review scope on the first pass too.
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(".config/spec-kit-llm-client/review-pipeline.yml")
        runs: list[str] = []

        def collect(steps):
            for step in steps:
                run = step.get("run")
                if isinstance(run, str):
                    runs.append(run)
                for branch in ("steps", "then", "else"):
                    nested = step.get(branch)
                    if isinstance(nested, list):
                        collect(nested)

        collect(parsed["steps"])
        total = sum(
            run.count("review only that git diff and also run git status")
            for run in runs
        )
        self.assertEqual(total, 4)
        self.assertIn("new files appear only in git status", " ".join(runs))

    def test_review_workflow_order(self):
        self.assertEqual(self.install(), 0)
        review = (self.home / ".config/spec-kit-llm-client/review-pipeline.yml").read_text(
            encoding="utf-8"
        )
        order = [
            review.index(f"- id: {s}")
            for s in (
                "generate-task-id",
                "determine-scope",
                "srp-loop",
                "srp-pass-check",
                "bug-loop",
                "bug-pass-check",
                "review-loop",
                "pass-check",
                "comment-review-loop",
                "comment-pass-check",
                "report",
            )
        ]
        self.assertEqual(order, sorted(order))

    def test_workflow_saves_adr_to_adr_dir(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: save-adr", workflow)
        self.assertIn('save_adr.py" save', workflow)
        self.assertIn('"{{ inputs.adr_dir }}"', workflow)
        self.assertIn("save_adr.py", workflow)
        self.assertNotIn("translit", workflow.lower().replace("transliteration", ""))
        self.assertNotIn("adr.md still has no 'slug' field", workflow)
        save_index = workflow.index("- id: save-adr")
        questions_index = workflow.index("- id: executor-questions")
        self.assertLess(save_index, questions_index)
        save_adr = (self.home / ".config/opencode/scripts/save_adr.py").read_text(encoding="utf-8")
        self.assertIn("read_slug", save_adr)
        self.assertIn("has no 'slug' field", save_adr)
        self.assertNotIn("translit", save_adr.lower().replace("transliteration", ""))
        # The slug/numbering/heading text rules live in adr_utils.py.
        adr_utils = (self.home / ".config/opencode/scripts/adr_utils.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("must contain ASCII letters", adr_utils)
        self.assertIn("w[:60]", adr_utils)

    def test_workflow_deviation_sync(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: sync-adr", workflow)
        self.assertIn("deviation.md", workflow)
        self.assertIn("## Amendments", workflow)
        block = workflow.split("- id: sync-adr", 1)[1].split("\n  - id:", 1)[0]
        self.assertIn("set -euo pipefail", block)
        self.assertIn('save_adr.py" sync', block)
        self.assertLess(block.index('save_adr.py" sync'), block.index("rm -f"))
        self.assertIn("timeout: 7200", block)
        save_adr = (self.home / ".config/opencode/scripts/save_adr.py").read_text(encoding="utf-8")
        self.assertIn("adr-saved.txt", save_adr)
        sync_index = workflow.index("- id: sync-adr")
        pass_index = workflow.index("- id: pass-check")
        review_loop_index = workflow.index("- id: review-loop")
        self.assertLess(review_loop_index, sync_index)
        self.assertLess(sync_index, pass_index)

    def test_workflow_approval_gate_after_loop(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: adr-unapproved", workflow)
        self.assertIn("- id: adr-approval-gate", workflow)
        parsed = self.parsed_workflow()
        approval = self.find_step(parsed["steps"], "adr-approval-gate")
        self.assertIsNotNone(approval)
        self.assertEqual(approval["type"], "gate")
        self.assertEqual(approval["options"], ["approve", "abort"])
        adr_unapproved = self.find_step(parsed["steps"], "adr-unapproved")
        self.assertIn("steps.adr-gate.output.choice", adr_unapproved["condition"])
        loop_index = workflow.index("- id: adr-loop")
        unapproved_index = workflow.index("- id: adr-unapproved")
        save_index = workflow.index("- id: save-adr")
        self.assertLess(loop_index, unapproved_index)
        self.assertLess(unapproved_index, save_index)

    def test_workflow_validate_task_id(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: validate-task-id", workflow)
        self.assertLess(
            workflow.index("- id: validate-task-id"), workflow.index("- id: write-adr")
        )
        # The task_id input is inlined into double-quoted shell strings in
        # generate-task-id and save-adr, so anything outside [A-Za-z0-9_-]
        # must be rejected before any step embeds it. As with the feature,
        # the value is read as JSON data from the run's persisted inputs and
        # validated in python: interpolating the raw value into a shell
        # validation script is itself the injection vector (a task id like
        # `"; touch x; echo "` runs the touch while the step text renders).
        run = self.find_step(self.parsed_workflow()["steps"], "validate-task-id")["run"]
        self.assertIn("inputs.json", run)
        self.assertIn("re.fullmatch", run)
        self.assertNotIn("{{ inputs.task_id }}", run)
        self.assertNotIn("grep -qE", run)
        run_agent = (self.home / ".config/opencode/scripts/run-agent.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("^[A-Za-z0-9_-]+$", run_agent)

    def test_workflow_validate_feature(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: validate-feature", workflow)
        # The feature input is inlined into double-quoted shell strings in
        # generate-task-id and write-adr, so quotes/backticks/$/backslash
        # must be rejected before any step embeds it. The check must not
        # interpolate the feature into a heredoc (a feature line equal to the
        # delimiter would terminate it early and execute the remaining lines
        # as shell); instead the value is read as JSON data from the run's
        # persisted inputs and validated in python.
        self.assertIn("inputs.json", workflow)
        self.assertIn("python3 -c", workflow)
        self.assertIn(".specify/workflows/runs", workflow)
        self.assertIn("re.search", workflow)
        self.assertNotIn("<<'FEATURE_EOF'", workflow)
        # The validate step itself must not interpolate the feature into the
        # shell text (that is the injection vector the check exists to close).
        run = self.find_step(self.parsed_workflow()["steps"], "validate-feature")["run"]
        self.assertNotIn("{{ inputs.feature }}", run)
        # The run id must come from the workflow context, not from "newest
        # directory by mtime": a concurrent run, or a resumed run whose
        # directory keeps its original mtime, would make the newest-directory
        # lookup pick the wrong run and skip (or wrongly reject) this
        # validation.
        self.assertIn("{{ context.run_id }}", run)
        self.assertNotIn("ls -1t", run)
        self.assertNotIn("head -1", run)
        self.assertLess(
            workflow.index("- id: validate-feature"),
            workflow.index("- id: generate-task-id"),
        )

    def test_workflow_adr_revise_loop(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("adr-loop", workflow)
        self.assertIn("feedback.md", workflow)
        self.assertIn("adr-feedback-clear", workflow)
        parsed = self.parsed_workflow()
        adr_loop = self.find_step(parsed["steps"], "adr-loop")
        self.assertIsNotNone(adr_loop)
        self.assertEqual(adr_loop["type"], "do-while")
        # The ADR approve/revise/reject loop ceiling is configurable
        # (workflow.max_adr_iterations), written with the default value 3.
        self.assertEqual(adr_loop["max_iterations"], 3)
        self.assertIn("steps.adr-gate.output.choice", adr_loop["condition"])
        adr_gate = self.find_step(parsed["steps"], "adr-gate")
        self.assertEqual(adr_gate["type"], "gate")
        self.assertEqual(adr_gate["options"], ["approve", "revise", "reject"])
        self.assertEqual(adr_gate["verdict_input"], "adr_verdict")

    def test_workflow_adr_loop_ceiling_is_configurable(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_adr_iterations: 3", "max_adr_iterations: 7")
        )
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow()
        self.assertEqual(
            self.find_step(parsed["steps"], "adr-loop")["max_iterations"], 7
        )

    def test_workflow_agent_steps_have_timeout(self):
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow()
        for step in (
            "write-adr",
            "adr-revise",
            "executor-questions",
            "planner-answers",
            "implement",
            "implement-retry",
            "review",
            "fix",
            "sync-adr",
            "save-adr",
            "srp-review",
            "srp-fix",
            "bug-review",
            "bug-fix",
            "comment-review",
            "comment-fix",
        ):
            found = self.find_step(parsed["steps"], step)
            self.assertIsNotNone(found, step)
            self.assertEqual(found.get("timeout"), 7200, step)
        for step in (
            "implement-loop",
            "implement-verify",
            "implement-pass-check",
            "verdict",
            "pass-check",
            "adr-feedback-clear",
            "validate-task-id",
            "validate-feature",
            "generate-task-id",
            "srp-verdict",
            "srp-pass-check",
            "bug-verdict",
            "bug-pass-check",
            "comment-verdict",
            "comment-pass-check",
        ):
            found = self.find_step(parsed["steps"], step)
            self.assertIsNotNone(found, step)
            self.assertNotIn("timeout", found, step)

    def test_workflow_srp_loop_structure(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: srp-loop", workflow)
        self.assertIn("- id: srp-review", workflow)
        self.assertIn("- id: srp-verdict", workflow)
        self.assertIn("- id: srp-fix", workflow)
        self.assertIn("- id: srp-pass-check", workflow)
        srp_verdict_run = self.find_step(self.parsed_workflow()["steps"], "srp-verdict")["run"]
        self.assertIn(
            'check-review "{{ inputs.state_dir }}" "{{ inputs.task_id }}" srp', srp_verdict_run
        )
        srp_pass_run = self.find_step(self.parsed_workflow()["steps"], "srp-pass-check")["run"]
        self.assertIn("SRP REVIEW OK: final verdict PASS", srp_pass_run)
        self.assertIn("WARNING: SRP review loop exhausted", srp_pass_run)
        self.assertIn("{{ steps.srp-verdict.output.exit_code != 0 }}", workflow)
        parsed = self.parsed_workflow()
        srp_loop = self.find_step(parsed["steps"], "srp-loop")
        self.assertIsNotNone(srp_loop)
        self.assertEqual(srp_loop["max_iterations"], 5)
        self.assertIn("SRP: FIX", self.find_step(parsed["steps"], "srp-review")["run"])
        self.assertIsNotNone(self.find_step(parsed["steps"], "srp-fix-branch"))
        implement_index = workflow.index("- id: implement")
        srp_index = workflow.index("- id: srp-loop")
        srp_check_index = workflow.index("- id: srp-pass-check")
        review_index = workflow.index("- id: review-loop")
        self.assertLess(implement_index, srp_index)
        self.assertLess(srp_check_index, review_index)

    def test_workflow_implement_loop_structure(self):
        # ADR-0007: after implement, a verify loop guards against an executor
        # that made no changes; one retry prompt, then the run fails.
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: implement-loop", workflow)
        self.assertIn("- id: implement-verify", workflow)
        self.assertIn("- id: implement-retry-branch", workflow)
        self.assertIn("- id: implement-retry", workflow)
        self.assertIn("- id: implement-pass-check", workflow)
        implement_verify_run = self.find_step(
            self.parsed_workflow()["steps"], "implement-verify"
        )["run"]
        self.assertIn('check_implementation.py" check "{{ inputs.adr_dir }}"', implement_verify_run)
        retry_run = self.find_step(self.parsed_workflow()["steps"], "implement-retry")["run"]
        self.assertIn('"You didn\'t do changes."', retry_run)
        self.assertIn("IMPLEMENT OK: changes present", workflow)
        implement_pass_run = self.find_step(
            self.parsed_workflow()["steps"], "implement-pass-check"
        )["run"]
        self.assertIn("made no changes to the repository in two attempts", implement_pass_run)
        self.assertIn("{{ steps.implement-verify.output.exit_code != 0 }}", workflow)
        self.assertIn(".implement-retried", workflow)
        parsed = self.parsed_workflow()
        self.assertEqual(
            self.find_step(parsed["steps"], "implement-loop")["max_iterations"], 2
        )
        implement_index = workflow.index("- id: implement")
        loop_index = workflow.index("- id: implement-loop")
        srp_index = workflow.index("- id: srp-loop")
        pass_index = workflow.index("- id: implement-pass-check")
        self.assertLess(implement_index, loop_index)
        self.assertLess(loop_index, srp_index)
        self.assertLess(loop_index, pass_index)

    def test_workflow_implement_iterations_configurable(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace(
                "max_implement_iterations: 2", "max_implement_iterations: 3"
            )
        )
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow()
        self.assertEqual(
            self.find_step(parsed["steps"], "implement-loop")["max_iterations"], 3
        )

    def test_workflow_bug_loop_structure(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: bug-loop", workflow)
        self.assertIn("- id: bug-review", workflow)
        self.assertIn("- id: bug-verdict", workflow)
        self.assertIn("- id: bug-fix-branch", workflow)
        self.assertIn("- id: bug-fix", workflow)
        self.assertIn("- id: bug-pass-check", workflow)
        bug_verdict_run = self.find_step(self.parsed_workflow()["steps"], "bug-verdict")["run"]
        self.assertIn(
            'check-review "{{ inputs.state_dir }}" "{{ inputs.task_id }}" bugs', bug_verdict_run
        )
        bug_pass_run = self.find_step(self.parsed_workflow()["steps"], "bug-pass-check")["run"]
        self.assertIn("BUGS REVIEW OK: final verdict PASS", bug_pass_run)
        self.assertIn("WARNING: bug review loop exhausted", bug_pass_run)
        self.assertIn("{{ steps.bug-verdict.output.exit_code != 0 }}", workflow)
        parsed = self.parsed_workflow()
        bug_loop = self.find_step(parsed["steps"], "bug-loop")
        self.assertIsNotNone(bug_loop)
        self.assertEqual(bug_loop["max_iterations"], 5)
        self.assertIn("BUGS: FIX", self.find_step(parsed["steps"], "bug-review")["run"])
        self.assertIn("bug-review-N.md", self.find_step(parsed["steps"], "bug-review")["run"])
        self.assertIsNotNone(self.find_step(parsed["steps"], "bug-fix-branch"))
        srp_check_index = workflow.index("- id: srp-pass-check")
        bug_index = workflow.index("- id: bug-loop")
        review_index = workflow.index("- id: review-loop")
        self.assertLess(srp_check_index, bug_index)
        self.assertLess(bug_index, review_index)

    def test_workflow_comment_review_loop_structure(self):
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- id: comment-review-loop", workflow)
        self.assertIn("- id: comment-review", workflow)
        self.assertIn("- id: comment-verdict", workflow)
        self.assertIn("- id: comment-fix", workflow)
        self.assertIn("- id: comment-pass-check", workflow)
        comment_verdict_run = self.find_step(
            self.parsed_workflow()["steps"], "comment-verdict"
        )["run"]
        self.assertIn(
            'check-review "{{ inputs.state_dir }}" "{{ inputs.task_id }}" comment',
            comment_verdict_run,
        )
        comment_pass_run = self.find_step(
            self.parsed_workflow()["steps"], "comment-pass-check"
        )["run"]
        self.assertIn("COMMENT REVIEW OK: final verdict PASS", comment_pass_run)
        self.assertIn("WARNING: comment review loop exhausted", comment_pass_run)
        self.assertIn("{{ steps.comment-verdict.output.exit_code != 0 }}", workflow)
        parsed = self.parsed_workflow()
        comment_loop = self.find_step(parsed["steps"], "comment-review-loop")
        self.assertIsNotNone(comment_loop)
        self.assertEqual(comment_loop["max_iterations"], 5)
        comment_run = self.find_step(parsed["steps"], "comment-review")["run"]
        self.assertIn("VERDICT: FIX", comment_run)
        self.assertIn("Why a reader would be misled:", comment_run)
        self.assertIn("Verdict: COMMENT | REFACTOR", comment_run)
        self.assertIsNotNone(self.find_step(parsed["steps"], "comment-fix-branch"))
        pass_check_index = workflow.index("- id: pass-check")
        comment_index = workflow.index("- id: comment-review-loop")
        self.assertLess(pass_check_index, comment_index)

    def test_workflow_shell_blocks_are_syntactically_valid(self):
        # Every inline shell block must parse with /bin/sh (what specify uses).
        # Regression: determine-scope (review-pipeline) used a folded >- block
        # with #-comments inside; folding joins all lines with spaces, so the
        # comment swallowed the rest of the script (unclosed `if`).
        if shutil.which("sh") is None:
            self.skipTest("sh not available")
        self.assertEqual(self.install(), 0)
        for rel in (
            ".config/spec-kit-llm-client/adr-pipeline.yml",
            ".config/spec-kit-llm-client/review-pipeline.yml",
        ):
            workflow = self.parsed_workflow(rel)
            for step_id, run in self.shell_runs(workflow["steps"]):
                proc = subprocess.run(
                    ["sh", "-n", "-c", run],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    proc.returncode,
                    0,
                    msg=f"{rel} step {step_id!r} fails sh -n:\n{proc.stderr}",
                )


class VerifyInstallTest(InstallerTestCase):
    """verify.verify_install: all errors are collected, and specify-version
    failures degrade to the documented messages."""

    def test_verify_collects_all_errors(self):
        layout = paths.build_paths(str(self.home))
        (self.home / ".config/opencode/agent").mkdir(parents=True)
        run_agent = self.home / ".config/opencode/scripts/run-agent.sh"
        run_agent.parent.mkdir(parents=True)
        run_agent.touch()
        run_agent.chmod(0o755)

        def run_fake(cmd, cwd=None, env=None, check=True):
            if cmd[1:3] == ["workflow", "run"]:
                return FakeResult(1, "", "Error: Required input 'feature' not provided.\n")
            if cmd[-3:] == ["opencode", "agent", "list"]:
                return FakeResult(0, "build (primary)\n")
            return FakeResult(0)

        with (
            mock.patch.object(proc, "run", side_effect=run_fake),
            self.assertRaises(InstallError) as cm,
        ):
            verify.verify_install(layout)
        err = str(cm.exception)
        self.assertIn("planner", err)
        self.assertIn("executor", err)
        self.assertIn("save_adr.py", err)
        self.assertIn("check_review.py", err)
        self.assertIn("adr_utils.py", err)

    def test_verify_workflow_syntax_specify_off_path(self):
        self.assertEqual(self.install(), 0)
        layout = paths.build_paths(str(self.home))

        def which_off_specify(name):
            if name == "specify":
                return None
            return which_fake(name)

        with (
            mock.patch.object(tool_discovery, "find_in_path", side_effect=which_off_specify),
            mock.patch.object(
                versions,
                "latest_specify_version",
                return_value=((0, 16), "/home/u/.local/bin/specify"),
            ),
            self.assertRaises(InstallError) as cm,
        ):
            verify.verify_install(layout)
        err = str(cm.exception)
        self.assertIn("'specify' not found on PATH", err)
        self.assertIn("/home/u/.local/bin/specify", err)


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
            ".config/opencode/scripts/run-pipeline.py",
            ".config/opencode/scripts/victory.wav",
            ".config/opencode/scripts/save_adr.py",
            ".config/opencode/scripts/check_review.py",
            ".config/opencode/scripts/check_implementation.py",
            ".config/opencode/scripts/task_utils.py",
            ".config/opencode/scripts/adr_utils.py",
            ".config/opencode/scripts/agent_call.py",
            ".config/spec-kit-llm-client/adr-pipeline.yml",
            ".config/spec-kit-llm-client/config.example.yml",
            ".config/spec-kit-llm-client/install-path.txt",
            ".local/bin/spec-run",
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


class UpdateApplyTest(InstallerTestCase):
    """--apply re-renders from the existing config and --update reports new
    options; conflicting subcommand flags are rejected up front."""

    def test_flag_conflicts_rejected(self):
        cases = [
            ["--uninstall", "--update"],
            ["--apply", "--uninstall"],
            ["--apply", "--update"],
        ]
        for extra in cases:
            rc, err = self.run_main(["--home", str(self.home), *extra])
            self.assertEqual(rc, 1, extra)
            self.assertIn("error:", err)

    def test_apply_rerenders_from_current_config(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_fix_iterations: 5", "max_fix_iterations: 9")
        )
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            rc = self.run_main(["--home", str(self.home), "--apply"])[0]
        self.assertEqual(rc, 0)
        # --apply is quiet: no status lines, path warning or next-steps.
        self.assertNotIn("Next steps", stdout.getvalue())
        self.assertNotIn("installation verified", stdout.getvalue())
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("max_iterations: 9", workflow)

    def test_apply_invalid_config_fails(self):
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_fix_iterations: 5", "max_fix_iterations: true")
        )
        rc, err = self.run_main(["--home", str(self.home), "--apply"])
        self.assertEqual(rc, 1)
        self.assertIn("max_fix_iterations must be an integer", err)

    def test_apply_skips_prerequisite_checks(self):
        # --apply re-renders from the existing config without the install-time
        # python3/opencode presence checks, so it works even when opencode is
        # not on PATH (the verify subprocesses still run, faked here).
        self.assertEqual(self.install(), 0)

        def which_no_opencode(name):
            if name == "opencode":
                return None
            return which_fake(name)

        rc, err = self.run_main(["--home", str(self.home), "--apply"], which=which_no_opencode)
        self.assertEqual(rc, 0, err)

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


if __name__ == "__main__":
    unittest.main()
