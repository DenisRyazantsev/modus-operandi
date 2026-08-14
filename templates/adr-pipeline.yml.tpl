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
    required: true
    prompt: "Short id for this task (used for artifacts and sessions)"
${verdict_inputs_decl}

steps:
  - id: write-adr
    type: shell
    timeout: ${step_timeout}
    run: >-
      "${run_agent}" planner
      "Write an ADR for the following feature into ${state_dir}/tasks/{{ inputs.task_id }}/adr.md
      with sections: Context, Decision, Alternatives, Consequences, Acceptance Criteria.
      Feature: {{ inputs.feature }}" --task {{ inputs.task_id }}

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
        show_file: "${state_dir}/tasks/{{ inputs.task_id }}/adr.md"
${approve_adr_verdict}
      - id: adr-revise-branch
        type: if
        condition: "{{ steps.adr-gate.output.choice == 'revise' }}"
        then:
          - id: adr-feedback-gate
            type: gate
            message: >-
              Write your feedback into ${state_dir}/tasks/{{ inputs.task_id }}/feedback.md,
              then choose continue. The planner will update adr.md accordingly.
            options: [continue, abort]
          - id: adr-revise
            type: shell
            timeout: ${step_timeout}
            run: >-
              "${run_agent}" planner
              "Read ${state_dir}/tasks/{{ inputs.task_id }}/feedback.md. If it contains
              feedback, update ${state_dir}/tasks/{{ inputs.task_id }}/adr.md accordingly.
              If it is empty or missing, do nothing." --task {{ inputs.task_id }}
          - id: adr-feedback-clear
            type: shell
            run: "rm -f ${state_dir}/tasks/{{ inputs.task_id }}/feedback.md"

  - id: save-adr
    type: shell
    run: |
      python3 - <<'PY'
      import os, re, glob
      p = "${state_dir}/tasks/{{ inputs.task_id }}/adr.md"
      if not os.path.exists(p):
          raise SystemExit("adr.md not found")
      text = open(p, encoding="utf-8").read()
      fm = text.split("---", 2)
      slug = None
      if len(fm) >= 3:
          m = re.search(r"^slug:\s*(\S+)", fm[1], re.M)
          if m:
              slug = re.sub(r"[^a-z0-9-]", "-", m.group(1).lower()).strip("-")
      if not slug:
          m = re.search(r"^#\s*ADR(?:\s*-\s*\d+)?\s*:\s*(.+)$$", text, re.M)
          title = m.group(1).strip() if m else "adr"
          tr = {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh","з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"}
          title = "".join(tr.get(c.lower(), c if c.isalnum() else "-") for c in title)
          slug = re.sub(r"-+", "-", title).strip("-").lower()
          slug = "-".join(w for w in slug.split("-") if w)[:60]
      adr_dir = "${adr_dir}"
      existing = glob.glob(os.path.join(adr_dir, "ADR-*-" + slug + ".md"))
      saved_path = ""
      if existing:
          print("adr already saved: " + existing[0])
          saved_path = existing[0]
      else:
          nums = [int(m.group(1)) for m in (re.search(r"ADR-(\d{4})-", f) for f in glob.glob(os.path.join(adr_dir, "ADR-*.md"))) if m]
          num = max(nums) + 1 if nums else 1
          name = "ADR-%04d-%s.md" % (num, slug)
          target = os.path.join(adr_dir, name)
          os.makedirs(adr_dir, exist_ok=True)
          saved = re.sub(r"^#\s*ADR(?:\s*-\s*\d+)?\s*:\s*(.+)$$", lambda m: "# ADR-%04d: %s" % (num, m.group(1).strip()), text, count=1, flags=re.M)
          with open(target, "w", encoding="utf-8") as f:
              f.write(saved)
          print("saved adr: " + target)
          saved_path = target
      with open("${state_dir}/tasks/{{ inputs.task_id }}/adr-saved.txt", "w", encoding="utf-8") as f:
          f.write(saved_path)
      PY

  - id: executor-questions
    type: shell
    timeout: ${step_timeout}
    run: >-
      "${run_agent}" executor
      "Read ${state_dir}/tasks/{{ inputs.task_id }}/adr.md. If anything is ambiguous, write
      ${state_dir}/tasks/{{ inputs.task_id }}/questions.md whose first line is exactly
      'QUESTIONS: PRESENT' followed by your numbered questions, then stop. If everything is
      clear, write ${state_dir}/tasks/{{ inputs.task_id }}/questions.md with the first line
      exactly 'QUESTIONS: NONE'." --task {{ inputs.task_id }}

  - id: planner-answers
    type: shell
    timeout: ${step_timeout}
    run: >-
      "${run_agent}" planner
      "Read ${state_dir}/tasks/{{ inputs.task_id }}/questions.md. If its first line is
      'QUESTIONS: PRESENT', write ${state_dir}/tasks/{{ inputs.task_id }}/answers.md answering
      each question line-by-line in the same order. If it is 'QUESTIONS: NONE', write nothing."
      --task {{ inputs.task_id }}

  - id: implement
    type: shell
    timeout: ${step_timeout}
    run: >-
      "${run_agent}" executor
      "Implement the feature per ${state_dir}/tasks/{{ inputs.task_id }}/adr.md and
      ${state_dir}/tasks/{{ inputs.task_id }}/answers.md (if present). Then run the project's
      tests/linter if available. If you must deviate from the ADR (e.g. it describes
      something impossible or clearly suboptimal), write ${state_dir}/tasks/{{ inputs.task_id }}/deviation.md
      recording: what the ADR says, what you did instead, and why. Do not create the file
      when there is no deviation." --task {{ inputs.task_id }}

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
          "Review the git changes against ${state_dir}/tasks/{{ inputs.task_id }}/adr.md.
          First read ${state_dir}/tasks/{{ inputs.task_id }}/deviation.md if present: if it
          records a justified deviation from the ADR, evaluate the code against the ADR as
          amended by that deviation and do not report the deviation itself as a finding.
          If the deviation file is missing or unjustified, report the mismatch as a finding.
          Run git status, then git diff HEAD (includes staged changes). Write
          ${state_dir}/tasks/{{ inputs.task_id }}/review-N.md (N is the next number after the
          existing review files) with the first line exactly 'VERDICT: PASS' or
          'VERDICT: FIX' followed by actionable findings. The verdict must reflect the
          implemented code, not the ADR document." --task {{ inputs.task_id }}

      - id: fix
        type: shell
        timeout: ${step_timeout}
        run: >-
          "${run_agent}" executor
          "Read the latest ${state_dir}/tasks/{{ inputs.task_id }}/review-N.md and fix all its
          findings. Then run the project's tests/linter if available." --task {{ inputs.task_id }}

      - id: verdict
        type: shell
        continue_on_error: true
        run: >-
          last=$$(ls -1 ${state_dir}/tasks/{{ inputs.task_id }}/review-*.md 2>/dev/null
          | sort -V | tail -1) && head -1 "$$last" | grep -q '^VERDICT: PASS'

  - id: sync-adr
    type: shell
    run: |
      if [ -f "${state_dir}/tasks/{{ inputs.task_id }}/deviation.md" ]; then
      "${run_agent}" planner "Read ${state_dir}/tasks/{{ inputs.task_id }}/deviation.md and ${state_dir}/tasks/{{ inputs.task_id }}/adr.md. Update adr.md so it reflects the recorded deviation: append an '## Amendments' section (do not rewrite the Decision) noting what changed and why." --task {{ inputs.task_id }}
      python3 - <<'PY'
      import os, re
      p = "${state_dir}/tasks/{{ inputs.task_id }}/adr-saved.txt"
      if not os.path.exists(p):
          raise SystemExit("no adr-saved.txt")
      target = open(p, encoding="utf-8").read().strip()
      if not target or not os.path.exists(target):
          print("warning: saved adr not found at " + target)
      else:
          m = re.search(r"ADR-(\d{4})-", target)
          num = m.group(1) if m else "XXXX"
          text = open("${state_dir}/tasks/{{ inputs.task_id }}/adr.md", encoding="utf-8").read()
          saved = re.sub(r"^#\s*ADR(?:\s*-\s*\d+)?\s*:\s*(.+)$$", lambda m2: "# ADR-%s: %s" % (num, m2.group(1).strip()), text, count=1, flags=re.M)
          with open(target, "w", encoding="utf-8") as f:
              f.write(saved)
          print("adr synced: " + target)
      PY
      rm -f "${state_dir}/tasks/{{ inputs.task_id }}/deviation.md"
      else
      echo "no deviation recorded"
      fi

  - id: pass-check
    type: shell
    run: >-
      last=$$(ls -1 ${state_dir}/tasks/{{ inputs.task_id }}/review-*.md 2>/dev/null
      | sort -V | tail -1) && head -1 "$$last" | grep -q '^VERDICT: PASS'

  - id: copy-latest-review
    type: shell
    run: >-
      latest=$$(ls -1 ${state_dir}/tasks/{{ inputs.task_id }}/review-*.md 2>/dev/null
      | sort -V | tail -1) && cp "$$latest" ${state_dir}/tasks/latest-review-{{ inputs.task_id }}.md

  - id: final-gate
    type: gate
    message: "Review is clean — close?"
    options: [approve, reject]
    show_file: "${state_dir}/tasks/latest-review-{{ inputs.task_id }}.md"
${final_gate_verdict}
