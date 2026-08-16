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
        self.assertIn("{{ steps.merge-reports.output.exit_code != 0 }}", workflow)
        self.assertIn("continue_on_error: true", workflow)
        self.assertIn("check_review.py", workflow)
        self.assertIn('check_review.py" merge', workflow)
        merge_run = self.find_step(self.parsed_workflow()["steps"], "merge-reports")["run"]
        self.assertIn(
            'check_review.py" merge "{{ inputs.state_dir }}" "{{ inputs.task_id }}"',
            merge_run,
        )
        pass_check_run = self.find_step(self.parsed_workflow()["steps"], "pass-check")["run"]
        self.assertIn("REVIEW OK: all verdicts PASS", pass_check_run)
        self.assertIn("WARNING: review loop exhausted all iterations without pass", pass_check_run)
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
                fan = step.get("step")
                if isinstance(fan, dict) and isinstance(fan.get("run"), str):
                    runs.append(fan["run"])

        collect(parsed["steps"])
        all_runs = " ".join(runs)
        self.assertIn("id: review-pipeline", review)
        self.assertNotIn("inputs: {}", review)
        self.assertIn("branch-diff:", review)
        # ADR-0009: a warm-up step, then one parallel retry loop, then the
        # deterministic final pass-check; the agentic report step is gone.
        for step in (
            "generate-task-id",
            "determine-scope",
            "warm-planner",
            "review-fix-loop",
            "pass-check",
        ):
            self.assertIn(f"- id: {step}", review, step)
        self.assertNotIn("- id: report", review)
        self.assertNotIn("- id: srp-loop", review)
        self.assertNotIn("- id: bug-loop", review)
        self.assertNotIn("- id: review-loop", review)
        self.assertNotIn("- id: comment-review-loop", review)
        # The fan-out item runs each check in a fork of the warm session and
        # dispatches the per-kind prompt + rereview-vs-review on the snapshot.
        fan = self.find_step(parsed["steps"], "review-fan")
        self.assertIsNotNone(fan)
        check = fan["step"]
        check_run = check["run"]
        self.assertIn('run-agent.sh" planner --fork --prompt-file', check_run)
        for kind, prompt in (
            ("srp", "review/srp-review.md"),
            ("bugs", "review/bug-review.md"),
            ("review", "review/review.md"),
            ("comment", "review/comment-review.md"),
        ):
            self.assertIn(prompt, check_run, kind)
        self.assertIn("review/srp-rereview.md", check_run)
        self.assertIn("-snapshot.sha", check_run)
        self.assertIn("git stash create", check_run)
        self.assertIn('merge "{{ inputs.state_dir }}" ""', all_runs)
        self.assertIn('pending "{{ inputs.state_dir }}" ""', all_runs)
        self.assertIn("fix-all.md", all_runs)
        # The warm-up is skipped on the cursor backend (no fork primitive).
        warm_run = self.find_step(parsed["steps"], "warm-planner")["run"]
        self.assertIn("SKLC_BACKEND", warm_run)
        self.assertIn('"cursor"', warm_run)
        self.assertIn("review/warmup.md", warm_run)
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
        # The merged review-report.md is the only writer of the name now.
        self.assertFalse(
            (self.home / ".config/spec-kit-llm-client/prompts/review/report.md").exists()
        )
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
            # The prompts are prose wrapped across lines (srp-rereview breaks
            # mid-phrase), so join the lines before substring checks.
            prompt = (prompts / f"{name}.md").read_text().replace("\n", " ")
            # The diff-enumeration wording differs per stage (srp-rereview
            # adds `--name-only`); the stable facts are the snapshot diff and
            # the git status ask, present in every re-review prompt.
            self.assertIn("run git diff @SNAP@", prompt)
            self.assertIn("git status", prompt)
            self.assertIn("does not show untracked files", prompt)

    def test_review_first_iteration_prompts_include_untracked_files(self):
        # Regression: determine-scope admits branches whose only changes are
        # untracked files, but the first-iteration prompts told the reviewer
        # to look only at `git diff <base>` — which is empty for untracked
        # files. Every first-iteration prompt must also ask for git status so
        # untracked files are in the review scope on the first pass too.
        self.assertEqual(self.install(), 0)
        prompts = self.home / ".config/spec-kit-llm-client/prompts/review"
        for name in ("srp-review", "bug-review", "review", "comment-review"):
            prompt = (prompts / f"{name}.md").read_text()
            # The wording differs per stage ("Run git status" in srp-review
            # vs "Also run git status" in the others); the shared guarantee
            # is that every prompt asks for git status so untracked files
            # enter the review scope.
            self.assertIn("git status", prompt)
            self.assertIn("new files appear only in git status", prompt)

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
                "warm-planner",
                "review-fix-loop",
                "pass-check",
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
        review_loop_index = workflow.index("- id: review-fix-loop")
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
            "fix-all",
            "sync-adr",
            "save-adr",
        ):
            found = self.find_step(parsed["steps"], step)
            self.assertIsNotNone(found, step)
            self.assertEqual(found.get("timeout"), 7200, step)
        for step in (
            "implement-loop",
            "implement-verify",
            "implement-pass-check",
            "pending-kinds",
            "merge-reports",
            "fix-branch",
            "pass-check",
            "adr-feedback-clear",
            "validate-task-id",
            "validate-feature",
            "generate-task-id",
        ):
            found = self.find_step(parsed["steps"], step)
            self.assertIsNotNone(found, step)
            self.assertNotIn("timeout", found, step)
        # The fan-out item template is an agent step too (ADR-0009): its
        # timeout must be patched with the configured shell timeout.
        fan = self.find_step(parsed["steps"], "review-fan")
        self.assertIsNotNone(fan)
        self.assertEqual(fan["step"].get("timeout"), 7200)

    def test_workflow_fan_out_item_timeout_is_patched(self):
        # The engine accepts only a literal timeout; the renderer's
        # _patch_workflow_numbers must reach into the fan-out `step:` template
        # and overwrite its literal with the configured shell_timeout.
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("shell_timeout: 7200", "shell_timeout: 1234")
        )
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow()
        fan = self.find_step(parsed["steps"], "review-fan")
        self.assertIsNotNone(fan)
        self.assertEqual(fan["step"].get("timeout"), 1234)

    def test_workflow_unified_review_loop_structure(self):
        # ADR-0009: the four sequential review loops (srp/bug/review/comment)
        # are replaced by one retry do-while whose fan-out runs only the
        # still-failing kinds in parallel forks of the warm planner session.
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/spec-kit-llm-client/adr-pipeline.yml").read_text(
            encoding="utf-8"
        )
        parsed = self.parsed_workflow()
        loop = self.find_step(parsed["steps"], "review-fix-loop")
        self.assertIsNotNone(loop)
        self.assertEqual(loop["type"], "do-while")
        self.assertEqual(loop["max_iterations"], 5)
        self.assertIn("steps.merge-reports.output.exit_code", loop["condition"])
        pending_run = self.find_step(parsed["steps"], "pending-kinds")["run"]
        self.assertIn(
            'check_review.py" pending "{{ inputs.state_dir }}" "{{ inputs.task_id }}"',
            pending_run,
        )
        fan = self.find_step(parsed["steps"], "review-fan")
        self.assertIsNotNone(fan)
        self.assertEqual(fan["type"], "fan-out")
        self.assertEqual(fan["max_concurrency"], 4)
        self.assertIn("{{ steps.pending-kinds.output.stdout | from_json }}", fan["items"])
        check = fan["step"]
        self.assertEqual(check["id"], "check")
        self.assertEqual(check.get("timeout"), 7200)
        check_run = check["run"]
        self.assertIn('run-agent.sh" planner --fork --prompt-file', check_run)
        # The item dispatches on {{ item }}: per-kind report prefix, prompt
        # file and PASS marker via check_review.py.
        kind_prompts = {
            "srp": "PROMPT=adr/srp-review.md",
            "bugs": "PROMPT=adr/bug-review.md",
            "review": "PROMPT=adr/review.md",
            "comment": "PROMPT=adr/comment-review.md",
        }
        for kind, prefix in (
            ("srp", "srp-review"),
            ("bugs", "bug-review"),
            ("review", "review"),
            ("comment", "comment-review"),
        ):
            self.assertIn(prefix, check_run)
            self.assertIn(kind_prompts[kind], check_run)
        fix_all = self.find_step(parsed["steps"], "fix-all")
        self.assertIsNotNone(fix_all)
        self.assertIn("--prompt-file", fix_all["run"])
        self.assertIn("fix-all.md", fix_all["run"])
        # The four sequential loops and their per-kind pass-checks are gone.
        for old in (
            "srp-loop",
            "bug-loop",
            "review-loop",
            "comment-review-loop",
            "srp-pass-check",
            "bug-pass-check",
            "comment-pass-check",
        ):
            self.assertNotIn(old, workflow)
        # The per-type fix prompts are no longer invoked (ADR-0009).
        for old_fix in ('srp-fix.md"', 'bug-fix.md"', 'comment-fix.md"', '"$PROMPTS_DIR/fix.md"'):
            self.assertNotIn(old_fix, workflow)
        implement_index = workflow.index("- id: implement-pass-check")
        loop_index = workflow.index("- id: review-fix-loop")
        sync_index = workflow.index("- id: sync-adr")
        pass_index = workflow.index("- id: pass-check")
        self.assertLess(implement_index, loop_index)
        self.assertLess(loop_index, sync_index)
        self.assertLess(sync_index, pass_index)

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
        review_loop_index = workflow.index("- id: review-fix-loop")
        pass_index = workflow.index("- id: implement-pass-check")
        self.assertLess(implement_index, loop_index)
        self.assertLess(loop_index, review_loop_index)
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

    def test_workflow_per_kind_review_prompts_still_ship(self):
        # ADR-0009 retires the per-kind FIX prompts and the sequential loops,
        # but the four per-kind REVIEW prompts are still the prompt files the
        # parallel fan-out dispatches on (one per kind).
        self.assertEqual(self.install(), 0)
        adr_prompts = self.home / ".config/spec-kit-llm-client/prompts/adr"
        self.assertIn(
            "SRP: FIX",
            (adr_prompts / "srp-review.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "BUGS: FIX",
            (adr_prompts / "bug-review.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "VERDICT: FIX",
            (adr_prompts / "review.md").read_text(encoding="utf-8"),
        )
        comment_prompt = (adr_prompts / "comment-review.md").read_text(encoding="utf-8")
        self.assertIn("VERDICT: FIX", comment_prompt)
        self.assertIn("Why a reader would be misled:", comment_prompt)
        self.assertIn("Verdict: COMMENT | REFACTOR", comment_prompt)

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
