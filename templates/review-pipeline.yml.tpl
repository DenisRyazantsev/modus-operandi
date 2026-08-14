schema_version: "1.0"
workflow:
  id: "review-pipeline"
  name: "Review Pipeline"
  version: "1.1.0"
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
      # `git diff --quiet` ignores untracked files, so a branch (or fresh
      # repo) containing only NEW files would falsely report "no changes";
      # count untracked files as changes too.
      if git diff "$$base" --quiet && [ -z "$$(git ls-files --others --exclude-standard)" ]; then
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
          snapfile="${state_dir}/tasks/current/srp-snapshot.sha";
          if [ -s "$$snapfile" ]; then
          snap=$$(cat "$$snapfile");
          "${run_agent}" planner
          "Re-review for SRP ONLY. The executor fixed the findings from the latest srp-review file. Verify each finding is fixed and review ONLY the changes made since the previous review: run git diff $$snap and git status (git diff does not show untracked files, so new files made by the executor only appear in git status). Skip files with fewer than 300 lines of code. Write ${state_dir}/tasks/current/srp-review-N.md (N is the next number after the existing srp-review files) with the first line exactly 'SRP: PASS' or 'SRP: FIX' followed by findings.";
          else
          "${run_agent}" planner
          "Find SRP violations in the code: every class, function and module must have one clear responsibility, no god classes, no mixed concerns. Do not review bugs or style (a later stage does). Skip files with fewer than 300 lines of code. If ${state_dir}/scope.txt starts with 'branch-diff: ', review only that git diff and also run git status (git diff does not show untracked files, so new files appear only in git status — include them in the review scope). Write ${state_dir}/tasks/current/srp-review-N.md (N is the next number after the existing srp-review files) with the first line exactly 'SRP: PASS' or 'SRP: FIX' followed by actionable findings.";
          fi;
          snap=$$(git stash create 2>/dev/null || true);
          [ -n "$$snap" ] || snap=HEAD;
          printf '%s' "$$snap" > "$$snapfile";

      - id: srp-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${check_review}" check-review "${state_dir}" "" srp

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
      if last=$$(python3 "${check_review}" check-review "${state_dir}" "" srp 2>/dev/null); then
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
          snapfile="${state_dir}/tasks/current/bug-snapshot.sha";
          if [ -s "$$snapfile" ]; then
          snap=$$(cat "$$snapfile");
          "${run_agent}" planner
          "Re-review for bugs ONLY. The executor fixed the findings from the latest bug-review file. Verify each finding is fixed and review ONLY the changes made since the previous review: run git diff $$snap and git status (git diff does not show untracked files, so new files made by the executor only appear in git status). Write ${state_dir}/tasks/current/bug-review-N.md (N is the next number after the existing bug-review files) with the first line exactly 'BUGS: PASS' or 'BUGS: FIX' followed by findings.";
          else
          "${run_agent}" planner
          "Find bugs in the code: logic errors, wrong conditions, off-by-one and edge cases, unhandled errors, races, broken control flow, type/unit mismatches. Do not review SRP or style (other stages do). If ${state_dir}/scope.txt starts with 'branch-diff: ', review only that git diff and also run git status (git diff does not show untracked files, so new files appear only in git status — include them in the review scope). Write ${state_dir}/tasks/current/bug-review-N.md (N is the next number after the existing bug-review files) with the first line exactly 'BUGS: PASS' or 'BUGS: FIX' followed by actionable findings.";
          fi;
          snap=$$(git stash create 2>/dev/null || true);
          [ -n "$$snap" ] || snap=HEAD;
          printf '%s' "$$snap" > "$$snapfile";

      - id: bug-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${check_review}" check-review "${state_dir}" "" bugs

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
      if last=$$(python3 "${check_review}" check-review "${state_dir}" "" bugs 2>/dev/null); then
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
          snapfile="${state_dir}/tasks/current/review-snapshot.sha";
          if [ -s "$$snapfile" ]; then
          snap=$$(cat "$$snapfile");
          "${run_agent}" planner
          "Re-review. The executor fixed the findings from the latest review file. Verify each finding is fixed and review ONLY the changes made since the previous review: run git diff $$snap and git status (git diff does not show untracked files, so new files made by the executor only appear in git status). Write ${state_dir}/tasks/current/review-N.md (N is the next number after the existing review files) with the first line exactly 'VERDICT: PASS' or 'VERDICT: FIX' followed by findings.";
          else
          "${run_agent}" planner
          "Find correctness and quality issues the SRP and bug stages missed: broken logic, edge cases, unhandled errors, dead code, confusing naming. If ${state_dir}/scope.txt starts with 'branch-diff: ', review only that git diff and also run git status (git diff does not show untracked files, so new files appear only in git status — include them in the review scope). Write ${state_dir}/tasks/current/review-N.md (N is the next number after the existing review files) with the first line exactly 'VERDICT: PASS' or 'VERDICT: FIX' followed by actionable findings.";
          fi;
          snap=$$(git stash create 2>/dev/null || true);
          [ -n "$$snap" ] || snap=HEAD;
          printf '%s' "$$snap" > "$$snapfile";

      - id: verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${check_review}" check-review "${state_dir}" "" review

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
      if last=$$(python3 "${check_review}" check-review "${state_dir}" "" review 2>/dev/null); then
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
          snapfile="${state_dir}/tasks/current/comment-snapshot.sha";
          if [ -s "$$snapfile" ]; then
          snap=$$(cat "$$snapfile");
          "${run_agent}" planner
          "Re-review for readability traps ONLY. The executor fixed the findings from the latest comment-review file. Verify each finding is fixed and review ONLY the changes made since the previous review: run git diff $$snap and git status (git diff does not show untracked files, so new files made by the executor only appear in git status). Write ${state_dir}/tasks/current/comment-review-N.md (N is the next number after the existing comment-review files) with the first line exactly 'VERDICT: PASS' or 'VERDICT: FIX' followed by findings.";
          else
          "${run_agent}" planner
          "Find readability traps: correct but misleading code — comments that state the obvious or contradict the code (add or fix a why comment, never a what description), names so unclear they deserve a rename. Not bugs, not SRP. If ${state_dir}/scope.txt starts with 'branch-diff: ', review only that git diff and also run git status (git diff does not show untracked files, so new files appear only in git status — include them in the review scope). Write ${state_dir}/tasks/current/comment-review-N.md (N is the next number after the existing comment-review files) with the first line exactly 'VERDICT: PASS' or 'VERDICT: FIX' followed by actionable findings.";
          fi;
          snap=$$(git stash create 2>/dev/null || true);
          [ -n "$$snap" ] || snap=HEAD;
          printf '%s' "$$snap" > "$$snapfile";

      - id: comment-verdict
        type: shell
        continue_on_error: true
        run: >-
          python3 "${check_review}" check-review "${state_dir}" "" comment

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
      if last=$$(python3 "${check_review}" check-review "${state_dir}" "" comment 2>/dev/null); then
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
