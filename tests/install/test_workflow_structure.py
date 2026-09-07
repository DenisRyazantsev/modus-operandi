"""Tests for the installed workflow structures (task/review pipelines)."""

import shutil
import subprocess
from collections.abc import Iterator
from typing import Any

from .installer_test_case import InstallerTestCase

TASK_WF = ".config/modus-operandi/task-pipeline.yml"
REVIEW_WF = ".config/modus-operandi/review-pipeline.yml"


class WorkflowStructureTest(InstallerTestCase):
    """The installed task-pipeline.yml and review-pipeline.yml structures:
    step ids, ordering, inputs, loops, gate options and inline shell blocks."""

    def shell_runs(self, steps: Any) -> Iterator[tuple[Any, Any]]:
        for step in steps:
            if step.get("type") == "shell" and isinstance(step.get("run"), str):
                yield step["id"], step["run"]
            for branch in ("steps", "then", "else"):
                nested = step.get(branch)
                if isinstance(nested, list):
                    yield from self.shell_runs(nested)

    def test_workflow_input_defaults_stay_at_config_defaults(self) -> None:
        # state_dir/adr_dir are NOT baked: they are declared as optional
        # workflow inputs with the config default values, and the launcher
        # passes the configured values via -i at runtime.
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(TASK_WF)
        self.assertEqual(parsed["inputs"]["state_dir"]["default"], ".workflow")
        self.assertEqual(parsed["inputs"]["adr_dir"]["default"], "architecture")
        self.assertFalse(parsed["inputs"]["state_dir"].get("required"))
        self.assertFalse(parsed["inputs"]["adr_dir"].get("required"))

    def test_workflow_scripts_dir_has_fallback_for_direct_runs(self) -> None:
        # `specify workflow run <path> -i task=...` is a documented entry
        # point that does not go through run-pipeline.py: MO_SCRIPTS_DIR is
        # then unset, so every step referencing the scripts must expand to
        # the default install location instead of an empty prefix. The
        # expansion is the ONLY shell syntax a run: value may carry
        # (CONTRIBUTING.md), so a bare $MO_SCRIPTS_DIR without the fallback
        # is a violation.
        self.assertEqual(self.install(), 0)
        fallback = "${MO_SCRIPTS_DIR:-$HOME/.config/opencode/scripts}"

        def missing_fallback(steps: Any, missing: list[str]) -> None:
            for step in steps:
                run = step.get("run")
                if isinstance(run, str) and "$MO_SCRIPTS_DIR" in run and fallback not in run:
                    missing.append(step.get("id"))
                for branch in ("steps", "then", "else"):
                    nested = step.get(branch)
                    if isinstance(nested, list):
                        missing_fallback(nested, missing)
                fan = step.get("step")
                if isinstance(fan, dict):
                    missing_fallback([fan], missing)

        for rel in (TASK_WF, REVIEW_WF):
            parsed = self.parsed_workflow(rel)
            missing: list[str] = []
            missing_fallback(parsed["steps"], missing)
            self.assertEqual(missing, [], rel)

    def test_workflow_loop_and_pass_check_structure(self) -> None:
        self.assertEqual(self.install(), 0)
        workflow = (self.home / TASK_WF).read_text(encoding="utf-8")
        self.assertIn("do-while", workflow)
        self.assertIn("continue_on_error: true", workflow)
        self.assertIn("check_review.py", workflow)
        merge_run = self.find_step(self.parsed_workflow(TASK_WF)["steps"], "merge-reports")["run"]
        self.assertIn(
            'check_review.py" merge "{{ inputs.state_dir }}" "{{ inputs.task_id }}"',
            merge_run,
        )
        # CONTRIBUTING.md: pass-check calls pass-check.sh; the verdict loop
        # and the messages live in the installed script.
        pass_check_run = self.find_step(self.parsed_workflow(TASK_WF)["steps"], "pass-check")["run"]
        self.assertIn("pass-check.sh", pass_check_run)
        self.assertIn('"{{ inputs.state_dir }}"', pass_check_run)
        self.assertIn('"{{ inputs.task_id }}"', pass_check_run)
        pass_check_script = (self.home / ".config/opencode/scripts/pass-check.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("REVIEW OK: all verdicts PASS", pass_check_script)
        self.assertIn(
            "WARNING: review loop exhausted all iterations without pass", pass_check_script
        )
        self.assertIn("- id: fix-branch", workflow)
        self.assertNotIn("sort -V", workflow)

    def test_workflow_task_id_is_optional(self) -> None:
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(TASK_WF)
        task_id = parsed["inputs"]["task_id"]
        self.assertEqual(task_id["required"], False)
        self.assertNotIn("default", task_id)

    def test_review_workflow_structure(self) -> None:
        self.assertEqual(self.install(), 0)
        review = (self.home / REVIEW_WF).read_text(encoding="utf-8")
        parsed = self.parsed_workflow(REVIEW_WF)
        runs: list[str] = []

        def collect(steps: Any) -> None:
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
        # ADR-0017: the reviewers review in their own fresh sessions, so
        # there is no planner warm-up step: determine-scope, then one
        # parallel retry loop, then the deterministic final pass-check.
        for step in (
            "generate-task-id",
            "determine-scope",
            "review-fix-loop",
            "pass-check",
            "summary",
        ):
            self.assertIn(f"- id: {step}", review, step)
        self.assertNotIn("- id: report", review)
        self.assertNotIn("- id: srp-loop", review)
        self.assertNotIn("- id: bug-loop", review)
        self.assertNotIn("- id: review-loop", review)
        self.assertNotIn("- id: comment-review-loop", review)
        self.assertNotIn("- id: warm-planner", review)
        # CONTRIBUTING.md: the fan-out item calls review-check.sh with the
        # state_dir, the empty task id, the item and the "review" prompt
        # namespace; the per-kind prompt dispatch and the reviewer-session
        # invocation live in the installed script.
        fan = self.find_step(parsed["steps"], "review-fan")
        self.assertIsNotNone(fan)
        check = fan["step"]
        check_run = check["run"]
        self.assertIn("review-check.sh", check_run)
        self.assertIn('"{{ inputs.state_dir }}"', check_run)
        self.assertIn('"{{ item }}"', check_run)
        self.assertIn("review", check_run)
        review_check = (self.home / ".config/opencode/scripts/review-check.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('run-agent.sh" "$ROLE" --review-fork', review_check)
        self.assertIn("ROLE=reviewer-srp", review_check)
        self.assertIn("ROLE=reviewer-bugs", review_check)
        self.assertIn("ROLE=reviewer-review", review_check)
        self.assertIn("ROLE=reviewer-comment", review_check)
        self.assertIn("ROLE=reviewer-tests", review_check)
        self.assertNotIn("planner --review-fork", review_check)
        # The prompt namespace is parametrized: the yaml call passes "review",
        # the script picks review vs rereview from the per-kind snapshot.
        for prompt in (
            '"$PROMPT_NS/srp-review.md"',
            '"$PROMPT_NS/bug-review.md"',
            '"$PROMPT_NS/review.md"',
            '"$PROMPT_NS/comment-review.md"',
            '"$PROMPT_NS/tests-review.md"',
            '"$PROMPT_NS/srp-rereview.md"',
            '"$PROMPT_NS/bug-rereview.md"',
            '"$PROMPT_NS/review-rereview.md"',
            '"$PROMPT_NS/comment-rereview.md"',
            '"$PROMPT_NS/tests-rereview.md"',
        ):
            self.assertIn(prompt, review_check, prompt)
        self.assertIn("-snapshot.sha", review_check)
        self.assertIn("git stash create", review_check)
        self.assertIn('merge "{{ inputs.state_dir }}" ""', all_runs)
        self.assertIn('pending "{{ inputs.state_dir }}" ""', all_runs)
        self.assertIn("fix-all.md", all_runs)
        self.assertIn("summary.md", all_runs)
        # determine-scope logic lives in determine-scope.sh.
        determine = (self.home / ".config/opencode/scripts/determine-scope.sh").read_text(
            encoding="utf-8"
        )
        for needle in (
            "scope.txt",
            "refs/remotes/origin/HEAD",
            "origin/main",
            "origin/master",
            "no changes against",
            # `git diff --quiet` ignores untracked files, so a branch containing
            # only NEW files must not be rejected as "nothing to review".
            "git ls-files --others --exclude-standard",
            "branch-diff: ",
            "mode: full codebase review",
        ):
            self.assertIn(needle, determine, needle)
        # generate-task-id logic lives in review-task-id.sh.
        task_id_script = (self.home / ".config/opencode/scripts/review-task-id.sh").read_text(
            encoding="utf-8"
        )
        for needle in ("git branch --show-current", "date +%Y%m%d-%H%M", "ln -sfn"):
            self.assertIn(needle, task_id_script, needle)
        # The merged review-report.md is the only writer of the name now.
        self.assertFalse((self.home / ".config/modus-operandi/prompts/review/report.md").exists())
        self.assertNotIn("base=$(cat", all_runs)
        self.assertNotIn("adr.md", all_runs)
        self.assertNotIn("adr_dir", all_runs)
        self.assertNotIn("--task", all_runs)

    def test_review_rerun_prompts_include_git_status(self) -> None:
        # Regression: git diff <snapshot> never shows untracked files, so a
        # NEW file the executor creates while fixing a finding was invisible
        # in every subsequent re-review. Each re-review prompt must also ask
        # for git status so untracked files are in the review scope.
        self.assertEqual(self.install(), 0)
        prompts = self.home / ".config/modus-operandi/prompts/review"
        for name in (
            "srp-rereview",
            "bug-rereview",
            "review-rereview",
            "comment-rereview",
            "tests-rereview",
        ):
            # The prompts are prose wrapped across lines (srp-rereview breaks
            # mid-phrase), so join the lines before substring checks.
            prompt = (prompts / f"{name}.md").read_text().replace("\n", " ")
            # The diff-enumeration wording differs per stage (srp-rereview
            # adds `--name-only`); the stable facts are the snapshot diff and
            # the git status ask, present in every re-review prompt.
            self.assertIn("run git diff @SNAP@", prompt)
            self.assertIn("git status", prompt)
            self.assertIn("does not show untracked files", prompt)

    def test_review_first_iteration_prompts_include_untracked_files(self) -> None:
        # Regression: determine-scope admits branches whose only changes are
        # untracked files, but the first-iteration prompts told the reviewer
        # to look only at `git diff <base>` — which is empty for untracked
        # files. Every first-iteration prompt must also ask for git status so
        # untracked files are in the review scope on the first pass too.
        self.assertEqual(self.install(), 0)
        prompts = self.home / ".config/modus-operandi/prompts/review"
        for name in ("srp-review", "bug-review", "review", "comment-review", "tests-review"):
            prompt = (prompts / f"{name}.md").read_text()
            # The wording differs per stage ("Run git status" in srp-review
            # vs "Also run git status" in the others); the shared guarantee
            # is that every prompt asks for git status so untracked files
            # enter the review scope.
            self.assertIn("git status", prompt)
            self.assertIn("new files appear only in git status", prompt)

    def test_review_workflow_order(self) -> None:
        self.assertEqual(self.install(), 0)
        review = (self.home / REVIEW_WF).read_text(encoding="utf-8")
        order = [
            review.index(f"- id: {s}")
            for s in (
                "generate-task-id",
                "determine-scope",
                "review-fix-loop",
                "pass-check",
                "summary",
            )
        ]
        self.assertEqual(order, sorted(order))

    def test_workflow_saves_adr_to_adr_dir(self) -> None:
        self.assertEqual(self.install(), 0)
        workflow = (self.home / TASK_WF).read_text(encoding="utf-8")
        self.assertIn("- id: save-adr", workflow)
        self.assertIn('save_adr.py" save', workflow)
        self.assertIn('"{{ inputs.adr_dir }}"', workflow)
        self.assertIn("save_adr.py", workflow)
        # ADR-0015: the ADR is released once, at the END of the pipeline
        # (after the review loop, before the final pass-check), so the saved
        # file is the final version incorporating every agreed clarification.
        save_index = workflow.index("- id: save-adr")
        review_loop_index = workflow.index("- id: review-fix-loop")
        pass_index = workflow.index("- id: pass-check")
        self.assertLess(review_loop_index, save_index)
        self.assertLess(save_index, pass_index)
        save_adr = (self.home / ".config/opencode/scripts/save_adr.py").read_text(encoding="utf-8")
        self.assertIn("read_slug", save_adr)
        self.assertIn("has no 'slug' field", save_adr)
        self.assertNotIn("translit", save_adr.lower().replace("transliteration", ""))
        # The sync subcommand is gone (ADR-0015): the release runs once.
        self.assertNotIn("cmd_sync", save_adr)
        # The slug/numbering/heading text rules live in adr_utils.py.
        adr_utils = (self.home / ".config/opencode/scripts/adr_utils.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("must contain ASCII letters", adr_utils)
        self.assertIn("w[:60]", adr_utils)

    def test_workflow_plan_deviation_loop(self) -> None:
        # ADR-0015: the executor's deviation from plan.md is resolved inside
        # the plan-deviation-loop (check_plan_deviation.py -> planner
        # agreement -> executor continue); the sync-adr step is gone.
        self.assertEqual(self.install(), 0)
        workflow = (self.home / TASK_WF).read_text(encoding="utf-8")
        self.assertIn("- id: plan-deviation-loop", workflow)
        self.assertNotIn("- id: sync-adr", workflow)
        # CONTRIBUTING.md: the deviation check and the agreement steps live
        # in check_plan_deviation.py and the adr/ prompts.
        loop = self.find_step(self.parsed_workflow(TASK_WF)["steps"], "plan-deviation-loop")
        self.assertEqual(loop["type"], "do-while")
        # The ceiling is a literal: the loop is deliberately absent from
        # render.py's _LOOP_ITERATION_KEYS (like motivation-loop), so
        # _patch_workflow_numbers does not overwrite it.
        self.assertEqual(loop["max_iterations"], 3)
        self.assertIn("steps.deviation-check.output.exit_code", loop["condition"])
        check = self.find_step(self.parsed_workflow(TASK_WF)["steps"], "deviation-check")
        self.assertIn("check_plan_deviation.py", check["run"])
        self.assertIn('"{{ inputs.state_dir }}"', check["run"])
        self.assertIn('"{{ inputs.task_id }}"', check["run"])
        check_script = (self.home / ".config/opencode/scripts/check_plan_deviation.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("plan-deviation.md", check_script)
        self.assertIn("resolve_task_dir", check_script)
        agreement = self.find_step(self.parsed_workflow(TASK_WF)["steps"], "planner-agreement")
        self.assertEqual(agreement.get("timeout"), 7200)
        self.assertIn("agent-step.sh", agreement["run"])
        self.assertIn("planner", agreement["run"])
        continue_step = self.find_step(self.parsed_workflow(TASK_WF)["steps"], "implement-continue")
        self.assertEqual(continue_step.get("timeout"), 7200)
        self.assertIn("agent-step.sh", continue_step["run"])
        self.assertIn("executor", continue_step["run"])
        # The loop sits between implement and implement-loop.
        implement_index = workflow.index("- id: implement")
        loop_index = workflow.index("- id: plan-deviation-loop")
        implement_loop_index = workflow.index("- id: implement-loop")
        self.assertLess(implement_index, loop_index)
        self.assertLess(loop_index, implement_loop_index)
        # The saved ADR is released at the very end of the pipeline.
        save_index = workflow.index("- id: save-adr")
        pass_index = workflow.index("- id: pass-check")
        review_loop_index = workflow.index("- id: review-fix-loop")
        self.assertLess(review_loop_index, save_index)
        self.assertLess(save_index, pass_index)

    def test_workflow_validate_task_id(self) -> None:
        self.assertEqual(self.install(), 0)
        workflow = (self.home / TASK_WF).read_text(encoding="utf-8")
        self.assertIn("- id: validate-task-id", workflow)
        self.assertLess(workflow.index("- id: validate-task-id"), workflow.index("- id: write-adr"))
        # The task_id input is inlined into double-quoted shell strings in
        # generate-task-id and save-adr, so anything outside [A-Za-z0-9_-]
        # must be rejected before any step embeds it. CONTRIBUTING.md: the
        # step calls validate_inputs.py; the value is read as JSON data from
        # the run's persisted inputs and validated in python inside the
        # script — interpolating the raw value into the step text is itself
        # the injection vector (a task id like `"; touch x; echo "` would run
        # the touch while the step renders).
        run = self.find_step(self.parsed_workflow(TASK_WF)["steps"], "validate-task-id")["run"]
        self.assertIn("validate_inputs.py", run)
        self.assertIn("task-id", run)
        self.assertIn("{{ context.run_id }}", run)
        self.assertNotIn("{{ inputs.task_id }}", run)
        validator = (self.home / ".config/opencode/scripts/validate_inputs.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("inputs.json", validator)
        self.assertIn("re.fullmatch", validator)
        self.assertNotIn("grep -qE", validator)
        run_agent = (self.home / ".config/opencode/scripts/run-agent.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("^[A-Za-z0-9_-]+$", run_agent)

    def test_workflow_fan_out_item_timeout_is_patched(self) -> None:
        # The engine accepts only a literal timeout; the renderer's
        # _patch_workflow_numbers must reach into the fan-out `step:` template
        # and overwrite its literal with the configured shell_timeout.
        self.assertEqual(self.install(), 0)
        self.write_config(self.read_config().replace("shell_timeout: 7200", "shell_timeout: 1234"))
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(TASK_WF)
        fan = self.find_step(parsed["steps"], "review-fan")
        self.assertIsNotNone(fan)
        self.assertEqual(fan["step"].get("timeout"), 1234)

    def test_workflow_unified_review_loop_structure(self) -> None:
        # ADR-0009: the four sequential review loops (srp/bug/review/comment)
        # are replaced by one retry do-while whose fan-out runs only the
        # still-failing kinds in parallel forks of the warm planner session.
        self.assertEqual(self.install(), 0)
        workflow = (self.home / TASK_WF).read_text(encoding="utf-8")
        parsed = self.parsed_workflow(TASK_WF)
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
        self.assertEqual(fan["max_concurrency"], 5)
        self.assertIn("{{ steps.pending-kinds.output.stdout | from_json }}", fan["items"])
        check = fan["step"]
        self.assertEqual(check["id"], "check")
        self.assertEqual(check.get("timeout"), 7200)
        # CONTRIBUTING.md: the item step calls review-check.sh with the state
        # dir, task id, item and the "adr" prompt namespace; the per-kind
        # dispatch (report prefix, prompt file, reviewer-role invocation)
        # lives in the installed script.
        check_run = check["run"]
        self.assertIn("review-check.sh", check_run)
        self.assertIn('"{{ inputs.state_dir }}"', check_run)
        self.assertIn('"{{ inputs.task_id }}"', check_run)
        self.assertIn('"{{ item }}"', check_run)
        self.assertIn("adr", check_run)
        review_check = (self.home / ".config/opencode/scripts/review-check.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('run-agent.sh" "$ROLE" --review-fork', review_check)
        self.assertNotIn("planner --review-fork", review_check)
        # The prompt namespace is parametrized: the yaml call passes "adr".
        for prompt in (
            '"$PROMPT_NS/srp-review.md"',
            '"$PROMPT_NS/bug-review.md"',
            '"$PROMPT_NS/review.md"',
            '"$PROMPT_NS/comment-review.md"',
            '"$PROMPT_NS/tests-review.md"',
        ):
            self.assertIn(prompt, review_check, prompt)
        for prefix in ("srp-review", "bug-review", "review", "comment-review", "tests-review"):
            self.assertIn(prefix, review_check)
        fix_all = self.find_step(parsed["steps"], "fix-all")
        self.assertIsNotNone(fix_all)
        self.assertIn("fix-all.md", fix_all["run"])
        # The executor prompt step goes through agent-step.sh (one script
        # call per step), which owns the --prompt-file delegation.
        agent_step = (self.home / ".config/opencode/scripts/agent-step.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--prompt-file", agent_step)
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
        save_index = workflow.index("- id: save-adr")
        pass_index = workflow.index("- id: pass-check")
        self.assertLess(implement_index, loop_index)
        self.assertLess(loop_index, save_index)
        self.assertLess(save_index, pass_index)

    def test_workflow_implement_loop_structure(self) -> None:
        # ADR-0007: after implement, a verify loop guards against an executor
        # that made no changes; one retry prompt, then the run fails.
        self.assertEqual(self.install(), 0)
        workflow = (self.home / TASK_WF).read_text(encoding="utf-8")
        self.assertIn("- id: implement-loop", workflow)
        self.assertIn("- id: implement-verify", workflow)
        self.assertIn("- id: implement-retry-branch", workflow)
        self.assertIn("- id: implement-retry", workflow)
        self.assertIn("- id: implement-pass-check", workflow)
        implement_verify_run = self.find_step(
            self.parsed_workflow(TASK_WF)["steps"], "implement-verify"
        )["run"]
        self.assertIn('check_implementation.py" check "{{ inputs.adr_dir }}"', implement_verify_run)
        # CONTRIBUTING.md: implement-retry calls implement-retry.sh; the
        # marker logic and the executor prompt live in the installed script.
        retry_run = self.find_step(self.parsed_workflow(TASK_WF)["steps"], "implement-retry")["run"]
        self.assertIn("implement-retry.sh", retry_run)
        self.assertIn('"{{ inputs.state_dir }}"', retry_run)
        retry_script = (self.home / ".config/opencode/scripts/implement-retry.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--prompt-file", retry_script)
        self.assertIn(".implement-retried", retry_script)
        self.assertIn("already retried once", retry_script)
        self.assertIn("adr/implement-retry.md", retry_script)
        self.assertIn(
            "You didn't do changes.",
            (self.home / ".config/modus-operandi/prompts/adr/implement-retry.md").read_text(),
        )
        # The IMPLEMENT OK / failure messages live in implement-pass-check.sh.
        pass_check_script = (
            self.home / ".config/opencode/scripts/implement-pass-check.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("IMPLEMENT OK: changes present", pass_check_script)
        self.assertIn("made no changes to the repository in two attempts", pass_check_script)
        self.assertIn("check_implementation.py", pass_check_script)
        self.assertIn("{{ steps.implement-verify.output.exit_code != 0 }}", workflow)
        self.assertIn("implement-pass-check.sh", workflow)
        parsed = self.parsed_workflow(TASK_WF)
        self.assertEqual(self.find_step(parsed["steps"], "implement-loop")["max_iterations"], 2)
        implement_index = workflow.index("- id: implement")
        loop_index = workflow.index("- id: implement-loop")
        review_loop_index = workflow.index("- id: review-fix-loop")
        pass_index = workflow.index("- id: implement-pass-check")
        self.assertLess(implement_index, loop_index)
        self.assertLess(loop_index, review_loop_index)
        self.assertLess(loop_index, pass_index)

    def test_workflow_implement_iterations_configurable(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_implement_iterations: 2", "max_implement_iterations: 3")
        )
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(TASK_WF)
        self.assertEqual(self.find_step(parsed["steps"], "implement-loop")["max_iterations"], 3)

    def test_workflow_per_kind_review_prompts_still_ship(self) -> None:
        # ADR-0009 retires the per-kind FIX prompts and the sequential loops,
        # but the five per-kind REVIEW prompts are still the prompt files the
        # parallel fan-out dispatches on (one per kind). The verdict markers
        # live in the reviewer role bodies (the agents' system prompts,
        # ADR-0017); the step prompts carry the review scope and the report
        # path.
        self.assertEqual(self.install(), 0)
        adr_prompts = self.home / ".config/modus-operandi/prompts/adr"
        for name in ("srp-review", "bug-review", "review", "comment-review", "tests-review"):
            prompt = (adr_prompts / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("@STATE_DIR@/tasks/current/plan.md", prompt)
            self.assertIn("@STATE_DIR@/tasks/current/adr.md", prompt)
            self.assertIn("@N@", prompt)
        roles = self.home / ".config/opencode/agent"
        self.assertIn(
            "SRP: PASS",
            (roles / "reviewer-srp.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "SRP: FIX",
            (roles / "reviewer-srp.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "BUGS: FIX",
            (roles / "reviewer-bugs.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "VERDICT: FIX",
            (roles / "reviewer-review.md").read_text(encoding="utf-8"),
        )
        comment_role = (roles / "reviewer-comment.md").read_text(encoding="utf-8")
        self.assertIn("VERDICT: FIX", comment_role)
        self.assertIn("Why a reader would be misled:", comment_role)
        self.assertIn("Verdict: COMMENT | REFACTOR", comment_role)

    def test_workflow_shell_blocks_are_syntactically_valid(self) -> None:
        # Every inline shell block must parse with /bin/sh (what specify uses).
        # Regression: determine-scope (review-pipeline) used a folded >- block
        # with #-comments inside; folding joins all lines with spaces, so the
        # comment swallowed the rest of the script (unclosed `if`).
        if shutil.which("sh") is None:
            self.skipTest("sh not available")
        self.assertEqual(self.install(), 0)
        for rel in (TASK_WF, REVIEW_WF):
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

    def test_review_workflow_summary_step(self) -> None:
        # ADR-0019: the review pipeline ends with the same executor summary
        # (empty task id, resolved through tasks/current).
        self.assertEqual(self.install(), 0)
        workflow = (self.home / REVIEW_WF).read_text(encoding="utf-8")
        parsed = self.parsed_workflow(REVIEW_WF)
        summary = self.find_step(parsed["steps"], "summary")
        self.assertIsNotNone(summary)
        self.assertIn("agent-step.sh", summary["run"])
        self.assertIn("executor", summary["run"])
        self.assertIn("summary.md", summary["run"])
        check = self.find_step(parsed["steps"], "summary-check")
        self.assertEqual(check.get("continue_on_error"), True)
        self.assertIn('check "{{ inputs.state_dir }}" ""', check["run"])
        branch = self.find_step(parsed["steps"], "summary-display")
        self.assertIn("steps.summary-check.output.exit_code == 0", branch["condition"])
        display = self.find_step(parsed["steps"], "summary-display-file")
        self.assertIn("show-file.sh", display["run"])
        self.assertIn('"tasks/current/summary.md"', display["run"])
        self.assertIn("--block summary", display["run"])
        self.assertLess(workflow.index("- id: pass-check"), workflow.index("- id: summary"))
