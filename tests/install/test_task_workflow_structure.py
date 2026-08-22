"""Tests for the installed task-pipeline.yml structure."""

from .installer_test_case import InstallerTestCase


class TaskPipelineStructureTest(InstallerTestCase):
    """The installed task-pipeline.yml structure: task phases (motivation ->
    research -> write-adr) plus the adr-pipeline tail with the
    executor-questions loop instead of the one-shot questions pair."""

    def test_task_workflow_exists_with_inputs(self) -> None:
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/modus-operandi/task-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("id: task-pipeline", workflow)
        parsed = self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")
        self.assertEqual(parsed["workflow"]["id"], "task-pipeline")
        inputs = parsed["inputs"]
        self.assertEqual(inputs["task"]["required"], True)
        self.assertEqual(inputs["task_id"]["required"], False)
        self.assertEqual(inputs["state_dir"]["default"], ".workflow")
        self.assertEqual(inputs["adr_dir"]["default"], "architecture")
        self.assertEqual(inputs["motivation_verdict"]["default"], "clear")
        self.assertEqual(inputs["motivation_verdict"]["enum"], ["", "clear", "clarify"])
        # The proposal agreement gate was removed (ADR-0011): the proposal
        # verdict input no longer exists.
        self.assertNotIn("proposal_verdict", inputs)

    def test_task_workflow_phases_use_planner_prompts(self) -> None:
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")
        for step_id, prompt in (
            ("study", "task/study.md"),
            ("study-revise", "task/study-revise.md"),
            ("research", "task/research.md"),
            ("write-adr", "task/write-adr.md"),
        ):
            step = self.find_step(parsed["steps"], step_id)
            self.assertIsNotNone(step, step_id)
            self.assertEqual(step["type"], "shell")
            self.assertIn("agent-step.sh", step["run"])
            self.assertIn("planner", step["run"])
            self.assertIn(prompt, step["run"], step_id)
        # The study step exports the task text for the prompt substitution.
        study = self.find_step(parsed["steps"], "study")
        self.assertIn('--export "TASK={{ inputs.task }}"', study["run"])

    def test_task_workflow_motivation_loop(self) -> None:
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")
        loop = self.find_step(parsed["steps"], "motivation-loop")
        self.assertIsNotNone(loop)
        self.assertEqual(loop["type"], "do-while")
        # The loop is effectively unlimited (ADR-0011): the literal ceiling
        # is written into the workflow and must survive any config.
        self.assertEqual(loop["max_iterations"], 100)
        self.assertIn("steps.motivation-gate.output.choice", loop["condition"])
        # study-display is the first step of the loop body: it prints the
        # full study.md, which the gate message embeds (the engine truncates
        # show_file at 200 lines, so the file is shown through the message).
        body = loop["steps"]
        self.assertEqual(body[0]["id"], "study-display")
        self.assertEqual(body[0]["type"], "shell")
        self.assertIn("show-file.sh", body[0]["run"])
        self.assertIn('"{{ inputs.state_dir }}"', body[0]["run"])
        self.assertIn('"tasks/current/study.md"', body[0]["run"])
        gate = self.find_step(parsed["steps"], "motivation-gate")
        self.assertEqual(gate["type"], "gate")
        self.assertEqual(gate["options"], ["clear", "clarify"])
        # No reject/abort choice by design (there is no later agreement
        # gate), so on_reject must not default to 'abort' (the engine's gate
        # validation requires one then): 'skip' documents that this gate
        # only records the choice.
        self.assertEqual(gate["on_reject"], "skip")
        self.assertEqual(gate["verdict_input"], "motivation_verdict")
        self.assertNotIn("show_file", gate)
        self.assertIn("steps.study-display.output.stdout", gate["message"])
        # The clarify branch mirrors the adr-loop revise branch.
        branch = self.find_step(parsed["steps"], "motivation-revise-branch")
        self.assertIn("steps.motivation-gate.output.choice == 'clarify'", branch["condition"])
        feedback_gate = self.find_step(parsed["steps"], "motivation-feedback-gate")
        self.assertEqual(feedback_gate["options"], ["continue", "abort"])
        self.assertIn("feedback-gate", feedback_gate["id"])
        clear = self.find_step(parsed["steps"], "motivation-feedback-clear")
        self.assertIn("clear-feedback.sh", clear["run"])
        # No final gate after the motivation loop: the loop exits on
        # 'clear' with no round limit.
        self.assertIsNone(self.find_step(parsed["steps"], "motivation-unapproved"))

    def test_task_workflow_has_no_proposal_gate(self) -> None:
        # The proposal agreement gate duplicates the motivation agreement and
        # was removed (ADR-0011): research goes straight to write-adr.
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/modus-operandi/task-pipeline.yml").read_text(
            encoding="utf-8"
        )
        parsed = self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")
        for old in (
            "proposal-loop",
            "proposal-gate",
            "proposal-revise-branch",
            "proposal-feedback-gate",
            "proposal-revise",
            "proposal-feedback-clear",
            "proposal-unapproved",
            "proposal-approval-gate",
        ):
            self.assertIsNone(self.find_step(parsed["steps"], old), old)
            self.assertNotIn(f"- id: {old}", workflow)
        self.assertNotIn("proposal_verdict", workflow)
        research_index = workflow.index("- id: research")
        write_index = workflow.index("- id: write-adr")
        self.assertLess(research_index, write_index)

    def test_task_workflow_has_no_adr_gate(self) -> None:
        # The proposal was already agreed before write-adr, so there is no
        # adr-loop/adr-gate: write-adr is followed directly by save-adr.
        self.assertEqual(self.install(), 0)
        workflow = (self.home / ".config/modus-operandi/task-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("- id: adr-loop", workflow)
        self.assertNotIn("- id: adr-gate", workflow)
        self.assertNotIn("adr_verdict", workflow)
        write_index = workflow.index("- id: write-adr")
        save_index = workflow.index("- id: save-adr")
        self.assertLess(write_index, save_index)

    def test_task_workflow_executor_questions_loop(self) -> None:
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")
        loop = self.find_step(parsed["steps"], "executor-questions-loop")
        self.assertIsNotNone(loop)
        self.assertEqual(loop["type"], "do-while")
        self.assertEqual(loop["max_iterations"], 3)
        self.assertIn("steps.questions-check.output.exit_code", loop["condition"])
        questions = self.find_step(parsed["steps"], "executor-questions")
        self.assertIn("agent-step.sh", questions["run"])
        self.assertIn("executor", questions["run"])
        self.assertIn("adr/executor-questions.md", questions["run"])
        check = self.find_step(parsed["steps"], "questions-check")
        self.assertEqual(check.get("continue_on_error"), True)
        self.assertIn("check_questions.py", check["run"])
        self.assertIn('check "{{ inputs.state_dir }}" "{{ inputs.task_id }}"', check["run"])
        branch = self.find_step(parsed["steps"], "questions-branch")
        self.assertIn("steps.questions-check.output.exit_code != 0", branch["condition"])
        answers = self.find_step(parsed["steps"], "planner-answers")
        self.assertIn("planner", answers["run"])
        self.assertIn("adr/planner-answers.md", answers["run"])
        # The one-shot questions pair of the adr-pipeline is gone: the steps
        # exist only nested inside the loop, never as top-level steps.
        top_level_ids = [s["id"] for s in parsed["steps"]]
        self.assertNotIn("executor-questions", top_level_ids)
        self.assertNotIn("planner-answers", top_level_ids)

    def _task_workflow_text(self) -> str:
        return (self.home / ".config/modus-operandi/task-pipeline.yml").read_text(encoding="utf-8")

    def test_task_workflow_tail_mirrors_adr_pipeline(self) -> None:
        self.assertEqual(self.install(), 0)
        workflow = self._task_workflow_text()
        for step in (
            "save-adr",
            "implement",
            "implement-loop",
            "implement-pass-check",
            "review-fix-loop",
            "sync-adr",
            "pass-check",
        ):
            self.assertIn(f"- id: {step}", workflow, step)
        order = [
            workflow.index(f"- id: {s}")
            for s in (
                "save-adr",
                "executor-questions-loop",
                "implement",
                "implement-loop",
                "implement-pass-check",
                "review-fix-loop",
                "sync-adr",
                "pass-check",
            )
        ]
        self.assertEqual(order, sorted(order))
        # The review fan-out uses the same "adr" prompt namespace as the
        # adr-pipeline tail.
        parsed = self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")
        check = self.find_step(parsed["steps"], "review-fan")["step"]
        self.assertIn("adr", check["run"])

    def test_task_workflow_loop_ceilings_are_configurable(self) -> None:
        self.assertEqual(self.install(), 0)
        self.write_config(
            self.read_config().replace("max_questions_iterations: 3", "max_questions_iterations: 7")
        )
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")
        self.assertEqual(
            self.find_step(parsed["steps"], "executor-questions-loop")["max_iterations"], 7
        )
        # The motivation loop ceiling is a literal (100), never config-driven:
        # no config key exists for it (ADR-0011).
        self.assertEqual(self.find_step(parsed["steps"], "motivation-loop")["max_iterations"], 100)
        self.assertNotIn("max_motivation_iterations", self.read_config())

    def test_task_workflow_validate_task(self) -> None:
        self.assertEqual(self.install(), 0)
        workflow = self._task_workflow_text()
        self.assertIn("- id: validate-task", workflow)
        run = self.find_step(
            self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")["steps"],
            "validate-task",
        )["run"]
        self.assertIn("validate_inputs.py", run)
        self.assertIn("task", run)
        self.assertIn("{{ context.run_id }}", run)
        self.assertNotIn("{{ inputs.task }}", run)
        self.assertLess(
            workflow.index("- id: validate-task"), workflow.index("- id: generate-task-id")
        )

    def test_task_workflow_generate_task_id_uses_task_text(self) -> None:
        self.assertEqual(self.install(), 0)
        run = self.find_step(
            self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")["steps"],
            "generate-task-id",
        )["run"]
        self.assertIn("adr-task-id.sh", run)
        self.assertIn('"{{ inputs.state_dir }}"', run)
        self.assertIn('"{{ inputs.task_id }}"', run)
        self.assertIn('"{{ inputs.task }}"', run)

    def test_task_workflow_agent_steps_have_timeout(self) -> None:
        self.assertEqual(self.install(), 0)
        parsed = self.parsed_workflow(".config/modus-operandi/task-pipeline.yml")
        for step in (
            "study",
            "study-revise",
            "research",
            "write-adr",
            "save-adr",
            "executor-questions",
            "planner-answers",
            "implement",
            "implement-retry",
            "fix-all",
            "sync-adr",
        ):
            found = self.find_step(parsed["steps"], step)
            self.assertIsNotNone(found, step)
            self.assertEqual(found.get("timeout"), 7200, step)
        for step in (
            "motivation-loop",
            "study-display",
            "motivation-gate",
            "motivation-feedback-gate",
            "motivation-feedback-clear",
            "executor-questions-loop",
            "questions-check",
            "questions-branch",
            "implement-loop",
            "implement-verify",
            "implement-pass-check",
            "pending-kinds",
            "merge-reports",
            "fix-branch",
            "pass-check",
            "validate-task-id",
            "validate-task",
            "generate-task-id",
        ):
            found = self.find_step(parsed["steps"], step)
            self.assertIsNotNone(found, step)
            self.assertNotIn("timeout", found, step)

    def test_task_workflow_prompts_ship(self) -> None:
        self.assertEqual(self.install(), 0)
        prompts = self.home / ".config/modus-operandi/prompts/task"
        for name in ("study", "study-revise", "research", "write-adr"):
            self.assertTrue((prompts / f"{name}.md").is_file(), name)
        # The proposal-revise prompt is gone with the proposal gate (ADR-0011).
        self.assertFalse((prompts / "proposal-revise.md").exists())
        study = (prompts / "study.md").read_text(encoding="utf-8")
        self.assertIn("study.md", study)
        self.assertIn("@TASK@", study)
        research = (prompts / "research.md").read_text(encoding="utf-8")
        self.assertIn("proposal.md", research)
        self.assertIn("web search", research)
        self.assertNotIn("shown to the human for approval", research)
        write_adr = (prompts / "write-adr.md").read_text(encoding="utf-8")
        self.assertIn("study.md", write_adr)
        self.assertIn("proposal.md", write_adr)
        self.assertIn("slug", write_adr)
        # The updated executor-questions prompt re-reads answers.md.
        executor_questions = (
            self.home / ".config/modus-operandi/prompts/adr/executor-questions.md"
        ).read_text(encoding="utf-8")
        self.assertIn("answers.md", executor_questions)
        self.assertIn("QUESTIONS: NONE", executor_questions)
