schema_version: "1.0"
workflow:
  id: "adr-pipeline"
  name: "ADR Pipeline"
  version: "1.0.0"
  author: "spec-kit-llm-client"
  description: "Planner -> executor cycle: ADR, questions, implementation, review-fix loop"

inputs:
  feature:
    type: string
    required: true
    prompt: "Describe what you want to build"
  task_id:
    type: string
    required: false
    prompt: "Short id for this task (optional; generated from the feature otherwise)"
${verdict_inputs_decl}

steps:
  - id: validate-task-id
    type: shell
    run: >-
      if [ -n "{{ inputs.task_id }}" ] && ! printf '%s' "{{ inputs.task_id }}" | grep -qE '^[A-Za-z0-9_-]+$$'; then
      echo "error: task_id '{{ inputs.task_id }}' contains unsupported characters; use only letters, digits, '_' or '-'" >&2; exit 1;
      fi

  - id: generate-task-id
    type: shell
    run: >-
      set -euo pipefail;
      mkdir -p "${state_dir}/tasks";
      if [ -n "{{ inputs.task_id }}" ]; then
      tid="{{ inputs.task_id }}";
      else
      slug=$$("${name_task}" "{{ inputs.feature }}");
      slug=$$(printf '%s' "$$slug" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$$//' | cut -c1-40);
      [ -n "$$slug" ] || slug=task;
      tid="$$slug-$$(date +%Y%m%d-%H%M)";
      fi;
      mkdir -p "${state_dir}/tasks/$$tid";
      ln -sfn "$$tid" "${state_dir}/tasks/current";
      echo "task id: $$tid";

  - id: write-adr
    type: shell
    timeout: ${step_timeout}
    run: >-
      "${run_agent}" planner
      "Write an ADR for the following feature into ${state_dir}/tasks/current/adr.md
      with sections: Context, Decision, Alternatives, Consequences, Acceptance Criteria.
      Feature: {{ inputs.feature }}"

  - id: adr-loop
    type: do-while
    max_iterations: 3
    condition: "{{ steps.adr-gate.output.choice != 'approve' }}"
    steps:
      - id: adr-gate
        type: gate
        message: "ADR is ready — approve, revise, or reject?"
        options: [approve, revise, reject]
        on_reject: abort
        show_file: "${state_dir}/tasks/current/adr.md"
${approve_adr_verdict}
      - id: adr-revise-branch
        type: if
        condition: "{{ steps.adr-gate.output.choice == 'revise' }}"
        then:
          - id: adr-feedback-gate
            type: gate
            message: >-
              Write your feedback into ${state_dir}/tasks/current/feedback.md,
              then choose continue. The planner will update adr.md accordingly.
            options: [continue, abort]
          - id: adr-revise
            type: shell
            timeout: ${step_timeout}
            run: >-
              "${run_agent}" planner
              "Read ${state_dir}/tasks/current/feedback.md. If it contains
              feedback, update ${state_dir}/tasks/current/adr.md accordingly.
              If it is empty or missing, do nothing."
          - id: adr-feedback-clear
            type: shell
            run: "rm -f ${state_dir}/tasks/current/feedback.md"

  - id: adr-unapproved
    type: if
    condition: "{{ steps.adr-gate.output.choice != 'approve' }}"
    then:
      - id: adr-approval-gate
        type: gate
        message: >-
          The ADR was not approved within the review rounds (last choice:
          {{ steps.adr-gate.output.choice }}). Approve it to save the ADR
          into ${adr_dir}/, or abort the run.
        options: [approve, abort]
        on_reject: abort
        show_file: "${state_dir}/tasks/current/adr.md"

  - id: save-adr
    type: shell
    timeout: ${step_timeout}
    run: >-
      python3 "${save_adr}" save "${state_dir}" "{{ inputs.task_id }}" "${adr_dir}" "${run_agent}"

  - id: executor-questions
    type: shell
    timeout: ${step_timeout}
    run: >-
      "${run_agent}" executor
      "Read ${state_dir}/tasks/current/adr.md. If anything is ambiguous, write
      ${state_dir}/tasks/current/questions.md whose first line is exactly
      'QUESTIONS: PRESENT' followed by your numbered questions, then stop. If everything is
      clear, write ${state_dir}/tasks/current/questions.md with the first line
      exactly 'QUESTIONS: NONE'."

  - id: planner-answers
    type: shell
    timeout: ${step_timeout}
    run: >-
      "${run_agent}" planner
      "Read ${state_dir}/tasks/current/questions.md. If its first line is
      'QUESTIONS: PRESENT', write ${state_dir}/tasks/current/answers.md answering
      each question line-by-line in the same order. If it is 'QUESTIONS: NONE', write nothing."
     

  - id: implement
    type: shell
    timeout: ${step_timeout}
    run: >-
      "${run_agent}" executor
      "Implement the feature per ${state_dir}/tasks/current/adr.md and
      ${state_dir}/tasks/current/answers.md (if present). Then run the project's
      tests/linter if available. If you must deviate from the ADR (e.g. it describes
      something impossible or clearly suboptimal), write ${state_dir}/tasks/current/deviation.md
      recording: what the ADR says, what you did instead, and why. Do not create the file
      when there is no deviation."

  - id: srp-loop
    type: do-while
    max_iterations: ${max_srp_iterations}
    condition: "{{ steps.srp-verdict.output.exit_code != 0 }}"
    steps:
      - id: srp-review
        type: shell
        timeout: ${step_timeout}
        run: >-
          "${run_agent}" planner
          "Review the git changes for SRP violations ONLY: the single-responsibility
          principle — every class, function and module must have one clear
          responsibility, with no god classes/functions and no mixed concerns in one
          unit. Do NOT review ADR compliance, tests, or any other quality aspect
          (a later stage does that). Run git status, then git diff HEAD (includes
          staged changes). Write ${state_dir}/tasks/current/srp-review-N.md
          (N is the next number after the existing srp-review files) with the first
          line exactly 'SRP: PASS' or 'SRP: FIX' followed by actionable findings."
         

      - id: srp-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${check_review}" check-review "${state_dir}" "{{ inputs.task_id }}" srp

      - id: srp-fix-branch
        type: if
        condition: "{{ steps.srp-verdict.output.exit_code != 0 }}"
        then:
          - id: srp-fix
            type: shell
            timeout: ${step_timeout}
            run: >-
              "${run_agent}" executor
              "Read the latest ${state_dir}/tasks/current/srp-review-N.md
              and fix all its SRP findings. Then run the project's tests/linter if
              available."

  - id: srp-pass-check
    type: shell
    run: >-
      if last=$$(python3 "${check_review}" check-review "${state_dir}" "{{ inputs.task_id }}" srp 2>/dev/null); then
      echo "SRP REVIEW OK: final verdict PASS ($$last)";
      else
      echo "WARNING: SRP review loop exhausted ${max_srp_iterations} iterations without 'SRP: PASS' (latest review: $${last:-none}); inspect the latest srp-review file and the code";
      fi

  - id: bug-loop
    type: do-while
    max_iterations: ${max_bug_iterations}
    condition: "{{ steps.bug-verdict.output.exit_code != 0 }}"
    steps:
      - id: bug-review
        type: shell
        timeout: ${step_timeout}
        run: >-
          "${run_agent}" planner
          "Review the git changes for BUGS ONLY: logic errors, wrong conditions,
          off-by-one and edge cases, unhandled errors, races, broken control flow,
          wrong types/units, and discrepancies between the implemented behavior and
          the acceptance criteria in ${state_dir}/tasks/current/adr.md.
          Do NOT review SRP violations, ADR-format compliance, or comment quality
          (later stages do that). Run git status, then git diff HEAD (includes
          staged changes). Write ${state_dir}/tasks/current/bug-review-N.md
          (N is the next number after the existing bug-review files) with the first
          line exactly 'BUGS: PASS' or 'BUGS: FIX' followed by actionable findings."
         

      - id: bug-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${check_review}" check-review "${state_dir}" "{{ inputs.task_id }}" bugs

      - id: bug-fix-branch
        type: if
        condition: "{{ steps.bug-verdict.output.exit_code != 0 }}"
        then:
          - id: bug-fix
            type: shell
            timeout: ${step_timeout}
            run: >-
              "${run_agent}" executor
              "Read the latest ${state_dir}/tasks/current/bug-review-N.md
              and fix all its bug findings. Then run the project's tests/linter if
              available."

  - id: bug-pass-check
    type: shell
    run: >-
      if last=$$(python3 "${check_review}" check-review "${state_dir}" "{{ inputs.task_id }}" bugs 2>/dev/null); then
      echo "BUGS REVIEW OK: final verdict PASS ($$last)";
      else
      echo "WARNING: bug review loop exhausted ${max_bug_iterations} iterations without 'BUGS: PASS' (latest review: $${last:-none}); inspect the latest bug-review file and the code";
      fi

  - id: review-loop
    type: do-while
    max_iterations: ${max_fix_iterations}
    condition: "{{ steps.verdict.output.exit_code != 0 }}"
    steps:
      - id: review
        type: shell
        timeout: ${step_timeout}
        run: >-
          "${run_agent}" planner
          "Review the git changes against ${state_dir}/tasks/current/adr.md.
          First read ${state_dir}/tasks/current/deviation.md if present: if it
          records a justified deviation from the ADR, evaluate the code against the ADR as
          amended by that deviation and do not report the deviation itself as a finding.
          If the deviation file is missing or unjustified, report the mismatch as a finding.
          Run git status, then git diff HEAD (includes staged changes). Write
          ${state_dir}/tasks/current/review-N.md (N is the next number after the
          existing review files) with the first line exactly 'VERDICT: PASS' or
          'VERDICT: FIX' followed by actionable findings. The verdict must reflect the
          implemented code, not the ADR document."

      - id: verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${check_review}" check-review "${state_dir}" "{{ inputs.task_id }}" review

      - id: fix-branch
        type: if
        condition: "{{ steps.verdict.output.exit_code != 0 }}"
        then:
          - id: fix
            type: shell
            timeout: ${step_timeout}
            run: >-
              "${run_agent}" executor
              "Read the latest ${state_dir}/tasks/current/review-N.md and fix all its
              findings. Then run the project's tests/linter if available."

  - id: sync-adr
    type: shell
    timeout: ${step_timeout}
    run: |
      set -euo pipefail
      if [ -f "${state_dir}/tasks/current/deviation.md" ]; then
      "${run_agent}" planner "Read ${state_dir}/tasks/current/deviation.md and ${state_dir}/tasks/current/adr.md. Update adr.md so it reflects the recorded deviation: append an '## Amendments' section (do not rewrite the Decision) noting what changed and why."
      python3 "${save_adr}" sync "${state_dir}" "{{ inputs.task_id }}"
      rm -f "${state_dir}/tasks/current/deviation.md"
      else
      echo "no deviation recorded"
      fi

  - id: pass-check
    type: shell
    run: >-
      if last=$$(python3 "${check_review}" check-review "${state_dir}" "{{ inputs.task_id }}" review 2>/dev/null); then
      echo "REVIEW OK: final verdict PASS ($$last)";
      else
      echo "WARNING: review loop exhausted ${max_fix_iterations} iterations without 'VERDICT: PASS' (latest review: $${last:-none}); inspect the latest review file and the code";
      fi

  - id: comment-review-loop
    type: do-while
    max_iterations: ${max_comment_iterations}
    condition: "{{ steps.comment-verdict.output.exit_code != 0 }}"
    steps:
      - id: comment-review
        type: shell
        timeout: ${step_timeout}
        run: >-
          "${run_agent}" planner
          "Review the git changes for readability 'traps' ONLY: places that are
          correct but would mislead a reader, NOT bugs. Act as a senior code
          reviewer opening this file for the first time: find only the spots where
          a reader would make a wrong assumption about what the code does and why
          it is written this way. Comment only the WHY, never the WHAT; apply the
          Chesterton's fence test (don't suggest removing things you don't yet
          understand); prefer a rename/refactor over a comment; judge against a
          typical reader of this codebase; if there are no findings return an empty
          list (noise is worse than silence). Check these triggers in order: magic
          numbers/constants, workarounds/hacks, non-standard API use, swallowed
          exceptions, edge cases, business rules inside conditions, implicit
          invariants, strange optimizations, external constraints, known
          limitations/tech debt. Run git status, then git diff HEAD (includes
          staged changes). Write ${state_dir}/tasks/current/comment-review-N.md
          (N is the next number after the existing comment-review files) with the
          first line exactly 'VERDICT: PASS' or 'VERDICT: FIX'. If PASS, write
          nothing else. If FIX, list findings in this strict format, one per block:
          <file:line>
          Why a reader would be misled: <one sentence>
          Comment: <1-2 lines, WHY only, in English>
          Verdict: COMMENT | REFACTOR"
         

      - id: comment-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${check_review}" check-review "${state_dir}" "{{ inputs.task_id }}" comment

      - id: comment-fix-branch
        type: if
        condition: "{{ steps.comment-verdict.output.exit_code != 0 }}"
        then:
          - id: comment-fix
            type: shell
            timeout: ${step_timeout}
            run: >-
              "${run_agent}" executor
              "Read the latest ${state_dir}/tasks/current/comment-review-N.md
              and apply all its findings: for each Verdict: COMMENT add the
              suggested why-comment to the code; for each Verdict: REFACTOR perform
              the rename/refactor instead of adding a comment. Then run the
              project's tests/linter if available."

  - id: comment-pass-check
    type: shell
    run: >-
      if last=$$(python3 "${check_review}" check-review "${state_dir}" "{{ inputs.task_id }}" comment 2>/dev/null); then
      echo "COMMENT REVIEW OK: final verdict PASS ($$last)";
      else
      echo "WARNING: comment review loop exhausted ${max_comment_iterations} iterations without 'VERDICT: PASS' (latest review: $${last:-none}); inspect the latest comment-review file and the code";
      fi
