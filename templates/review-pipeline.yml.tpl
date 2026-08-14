schema_version: "1.0"
workflow:
  id: "review-pipeline"
  name: "Review Pipeline"
  version: "1.0.0"
  author: "spec-kit-llm-client"
  description: "Review your code and fix findings; by default the whole codebase, with -i branch-diff=true only the changes between the current branch and the default branch"

inputs:
  branch-diff:
    type: string
    required: false
    prompt: "true to review only the changes between the current branch and the default branch (otherwise the whole codebase is reviewed)"

steps:
  - id: generate-task-id
    type: shell
    run: >-
      set -euo pipefail;
      mkdir -p "${state_dir}/tasks";
      branch=$$(git branch --show-current 2>/dev/null || true);
      slug=$$(printf '%s' "$${branch:-review}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$$//' | cut -c1-40);
      [ -n "$$slug" ] || slug=review;
      tid="$$slug-$$(date +%Y%m%d-%H%M)";
      mkdir -p "${state_dir}/tasks/$$tid";
      ln -sfn "$$tid" "${state_dir}/tasks/current";
      echo "task id: $$tid";

  - id: determine-scope
    type: shell
    run: >-
      set -euo pipefail;
      if [ "{{ inputs.branch-diff }}" = "true" ]; then
      base="";
      if git symbolic-ref -q refs/remotes/origin/HEAD >/dev/null 2>&1; then
      base=$$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/@@');
      fi;
      if [ -z "$$base" ]; then
      for b in origin/main origin/master main master; do
      if git rev-parse --verify --quiet "$$b" >/dev/null 2>&1; then base="$$b"; break; fi;
      done;
      fi;
      if [ -z "$$base" ]; then
      echo "WARNING: no main/master branch found; reviewing against HEAD";
      base="HEAD";
      fi;
      if git diff "$$base" --quiet; then
      echo "error: no changes against $$base - nothing to review" >&2; exit 1;
      fi;
      printf '%s' "$$base" > "${state_dir}/base-branch.txt";
      printf 'branch-diff: %s' "$$base" > "${state_dir}/scope.txt";
      echo "mode: branch-diff (base: $$base)";
      else
      rm -f "${state_dir}/base-branch.txt";
      printf 'full' > "${state_dir}/scope.txt";
      echo "mode: full codebase review";
      fi;

  - id: srp-loop
    type: do-while
    max_iterations: ${max_srp_iterations}
    condition: "{{ steps.srp-verdict.output.exit_code != 0 }}"
    steps:
      - id: srp-review
        type: shell
        timeout: ${step_timeout}
        run: >-
          set -euo pipefail;
          "${run_agent}" planner
          "Review for SRP violations ONLY: the single-responsibility principle —
          every class, function and module must have one clear responsibility, with
          no god classes/functions and no mixed concerns in one unit. Do NOT review
          bugs, tests, or any other quality aspect (a later stage does that).
          Review scope: read ${state_dir}/scope.txt — if it says 'full', review the
          ENTIRE codebase of this project (all source files; skip .git, .specify,
          build artifacts and dependencies); if it starts with 'branch-diff: ', the
          base branch name follows — run git status, then git diff <base> (includes
          staged and unstaged changes) and review ONLY those changes.
          Write ${state_dir}/tasks/current/srp-review-N.md
          (N is the next number after the existing srp-review files) with the first
          line exactly 'SRP: PASS' or 'SRP: FIX' followed by actionable findings."

      - id: srp-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${save_adr}" check-review "${state_dir}" "" srp

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
      if last=$$(python3 "${save_adr}" check-review "${state_dir}" "" srp 2>/dev/null); then
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
          set -euo pipefail;
          "${run_agent}" planner
          "Review for BUGS ONLY: logic errors, wrong conditions,
          off-by-one and edge cases, unhandled errors, races, broken control flow,
          wrong types/units, and mismatches between the implemented behavior and
          what the code is clearly meant to do.
          Do NOT review SRP violations, style, or comment quality
          (later stages do that).
          Review scope: read ${state_dir}/scope.txt — if it says 'full', review the
          ENTIRE codebase of this project (all source files; skip .git, .specify,
          build artifacts and dependencies); if it starts with 'branch-diff: ', the
          base branch name follows — run git status, then git diff <base> (includes
          staged and unstaged changes) and review ONLY those changes.
          Write ${state_dir}/tasks/current/bug-review-N.md
          (N is the next number after the existing bug-review files) with the first
          line exactly 'BUGS: PASS' or 'BUGS: FIX' followed by actionable findings."

      - id: bug-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${save_adr}" check-review "${state_dir}" "" bugs

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
      if last=$$(python3 "${save_adr}" check-review "${state_dir}" "" bugs 2>/dev/null); then
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
          set -euo pipefail;
          "${run_agent}" planner
          "Review for general correctness and quality: broken logic and control
          flow, edge cases, unhandled errors, dead code, confusing naming, and
          anything the earlier SRP and bug stages missed.
          Review scope: read ${state_dir}/scope.txt — if it says 'full', review the
          ENTIRE codebase of this project (all source files; skip .git, .specify,
          build artifacts and dependencies); if it starts with 'branch-diff: ', the
          base branch name follows — run git status, then git diff <base> (includes
          staged and unstaged changes) and review ONLY those changes.
          Write ${state_dir}/tasks/current/review-N.md (N is the
          next number after the existing review files) with the first line exactly
          'VERDICT: PASS' or 'VERDICT: FIX' followed by actionable findings."

      - id: verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${save_adr}" check-review "${state_dir}" "" review

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

  - id: pass-check
    type: shell
    run: >-
      if last=$$(python3 "${save_adr}" check-review "${state_dir}" "" review 2>/dev/null); then
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
          set -euo pipefail;
          "${run_agent}" planner
          "Review for readability 'traps' ONLY: correct but
          misleading code that would confuse a reader — comments that state the
          obvious or contradict the code (add or fix a *why* comment, never a
          *what* description), and names/structures so unclear they deserve a
          rename or refactor. NOT bugs, NOT SRP violations (later stages handle
          nothing after this — this is the last stage).
          Review scope: read ${state_dir}/scope.txt — if it says 'full', review the
          ENTIRE codebase of this project (all source files; skip .git, .specify,
          build artifacts and dependencies); if it starts with 'branch-diff: ', the
          base branch name follows — run git status, then git diff <base> (includes
          staged and unstaged changes) and review ONLY those changes.
          Write
          ${state_dir}/tasks/current/comment-review-N.md (N is the next number
          after the existing comment-review files) with the first line exactly
          'VERDICT: PASS' or 'VERDICT: FIX' followed by actionable findings."

      - id: comment-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${save_adr}" check-review "${state_dir}" "" comment

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
              and fix all its readability findings. Then run the project's
              tests/linter if available."

  - id: comment-pass-check
    type: shell
    run: >-
      if last=$$(python3 "${save_adr}" check-review "${state_dir}" "" comment 2>/dev/null); then
      echo "COMMENT REVIEW OK: final verdict PASS ($$last)";
      else
      echo "WARNING: comment review loop exhausted ${max_comment_iterations} iterations without 'VERDICT: PASS' (latest review: $${last:-none}); inspect the latest comment-review file and the code";
      fi

  - id: report
    type: shell
    timeout: ${step_timeout}
    run: >-
      set -euo pipefail;
      "${run_agent}" planner
      "Write ${state_dir}/tasks/current/review-report.md summarizing this review
      run: the review scope (read ${state_dir}/scope.txt — either 'full', meaning
      the whole codebase was reviewed, or the base branch the diff was taken
      against), the reviewed files, and per stage (SRP, bugs, general review,
      comments) what was found and what the executor fixed, ending with an
      overall verdict line exactly 'VERDICT: PASS' when nothing remains unfixed
      or 'VERDICT: REVIEW' when some findings could not be resolved. Read the
      latest srp-review-N.md, bug-review-N.md, review-N.md and
      comment-review-N.md files for the history."
