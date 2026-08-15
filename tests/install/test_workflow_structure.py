"""Tests for the installed workflow structures (adr/review pipelines)."""

import shutil
import subprocess

from .installer_test_case import InstallerTestCase


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
        report_prompt = (
            self.home / ".config/spec-kit-llm-client/prompts/review/report.md"
        ).read_text()
        self.assertIn("review-report.md", report_prompt)
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
        prompts = self.home / ".config/spec-kit-llm-client/prompts/review"
        for name in ("srp-rereview", "bug-rereview", "review-rereview", "comment-rereview"):
            prompt = (prompts / f"{name}.md").read_text()
            self.assertIn("run git diff @SNAP@ and git status", prompt)
            self.assertIn("does not show untracked files", prompt)

    def test_review_first_iteration_prompts_include_untracked_files(self):
        # Regression: determine-scope admits branches whose only changes are
        # untracked files, but the first-iteration prompts told the reviewer
        # to look only at `git diff <base>` — which is empty for untracked
        # files. Every first-iteration prompt must also ask for git status so
        # untracked files are in the review scope on the first pass too.
        self.assertEqual(self.install(), 0)
        prompts = self.home / ".config/spec-kit-llm-client/prompts/review"
        total = 0
        for name in ("srp-review", "bug-review", "review", "comment-review"):
            prompt = (prompts / f"{name}.md").read_text()
            self.assertIn("Also run git status", prompt)
            total += prompt.count("Also run git status")
        self.assertEqual(total, 4)
        for name in ("srp-review", "bug-review", "review", "comment-review"):
            self.assertIn(
                "new files appear only in git status",
                (prompts / f"{name}.md").read_text(),
            )

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
        sync_prompt = (
            self.home / ".config/spec-kit-llm-client/prompts/adr/sync-adr.md"
        ).read_text()
        self.assertIn("## Amendments", sync_prompt)
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
        srp_review_run = self.find_step(parsed["steps"], "srp-review")["run"]
        self.assertIn("--prompt-file", srp_review_run)
        self.assertIn(
            "SRP: FIX",
            (self.home / ".config/spec-kit-llm-client/prompts/adr/srp-review.md").read_text(),
        )
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
        self.assertIn("--prompt-file", retry_run)
        self.assertIn(
            "You didn't do changes.",
            (self.home / ".config/spec-kit-llm-client/prompts/adr/implement-retry.md").read_text(),
        )
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
        bug_review_run = self.find_step(parsed["steps"], "bug-review")["run"]
        self.assertIn("--prompt-file", bug_review_run)
        self.assertIn(
            "BUGS: FIX",
            (self.home / ".config/spec-kit-llm-client/prompts/adr/bug-review.md").read_text(),
        )
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
        self.assertIn("--prompt-file", comment_run)
        comment_prompt = (
            self.home / ".config/spec-kit-llm-client/prompts/adr/comment-review.md"
        ).read_text()
        self.assertIn("VERDICT: FIX", comment_prompt)
        self.assertIn("Why a reader would be misled:", comment_prompt)
        self.assertIn("Verdict: COMMENT | REFACTOR", comment_prompt)
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
