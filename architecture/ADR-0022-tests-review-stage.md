---
slug: tests-review-stage
status: accepted
date: 2026-09-07
---

# ADR-0022: Tests Review as a Fifth Kind of the Unified Review Loop in Both Pipelines

## Context

Executor-written tests are the only artifact of the pipeline that nobody verifies: the four review
kinds (SRP, bugs, general review, readability comments) review the code, not its tests. Tests that
do not exercise the changed behavior, assert nothing meaningful, mock by hand or violate range
boundaries pass silently and create false confidence — a regression can go undetected. The user
requires a new stage of the review phase that checks the executor's tests against explicit test
conventions and grounds the verdict in machine-produced reports, integrated as a part of the
existing parallel review phase. A detailed draft prompt specifies the conventions and the verdict
format.

## Decision

1. **Tests is the fifth review kind of the unified parallel review-fix loop of both pipelines**
   (the task pipeline and the review pipeline, including its branch-diff mode). It follows the
   established per-kind conventions: a dedicated reviewer role with its own fresh per-kind session
   on the planner's model, a report whose first line is exactly `TESTS: PASS` or `TESTS: FIX`,
   merging into the common review report, one common fix pass by the executor, rerunning only the
   failed kinds on the next iteration, and the shared iteration cap.
2. **Scope is the executor's changed code.** The reviewer checks only the tests that cover the
   code the executor added or modified (the diff, including untracked files); in the review
   pipeline the branch-diff scope applies the same way. What counts as public, internal and
   private API is determined by the reviewer from the project itself, not from a fixed list.
3. **The conventions enforced** are those of the draft prompt, transferred into the reviewer's
   rules with only the minimal adaptation needed to work in the pipeline (diff scoping and report
   path mechanics as in the other review kinds): every public entry point of the changed code must
   be invoked by at least one test; internal-API functions of changed modules whose behavior was
   added or extended must be covered by module-level tests (existing tests already covering the
   behavior are sufficient); no test may touch private members; parametrized tests must cover the
   minimum, the maximum and a middle value of each ranged parameter and assert the expected
   result, without exhaustive enumeration; mocks are allowed only for the three stated reasons
   (grossly slow, non-deterministic, irreversible side effects) and must replay state recorded
   from the real service rather than hand-invented responses; tests live in their module's own
   test scope; test latency is reported as informational `NOTE:` remarks only. A failing test
   suite is a FIX finding that stops further analysis of that area.
4. **Machine-produced reports are the evidence base.** The review rests on a function-call-level
   coverage report (split into public API and per-module internal API) and a latency report
   produced by the project's own test-process code — the reviewer never estimates coverage by
   reading. The reports must already exist when the reviewer starts: the executor generates them
   as part of the task (running the tests and the report generation after implementation). When a
   report is missing, the reviewer runs the project's report generator itself; no concrete command
   is passed in the step prompt — it must be discoverable from the project's own documentation.
   Reports are regenerated only when the code has changed (for example after the executor's
   fixes), never speculatively while nothing changed.
5. **Missing tooling degrades gracefully, and is built where needed.** The report generators are
   the executor's responsibility: it implements them when the project lacks them, or they already
   exist. For this repository the function-level coverage and latency generators are part of this
   task, so the stage can pass in the project's own runs. If a project's language has no
   function-coverage tooling at all — after the reviewer verifies that claim, not assumes it —
   the review is impossible and the check ends in `TESTS: PASS` with a warning naming the missing
   tooling, instead of failing forever.
6. **The review is project-independent.** Where a repository's own rules conflict with the
   conventions, the repository's rules win; the prompt is not adapted to any project's specific
   mock practices.

## Alternatives

- **A separate "check tests → fix tests" loop after the general review loop.** Rejected: the
  user considers the tests check part of the big review phase; a separate loop would duplicate the
  merge/fix/rerun mechanics and split fixes of one change across two passes.
- **Adding the tests check to the task pipeline only.** Rejected: review runs also modify code and
  tests; tests of files changed in a branch-diff review must be reviewable too.
- **The reviewer estimates coverage by reading tests and code, without machine reports.**
  Rejected: coverage claims from reading hallucinate; industry practice (assurance filters of
  LLM-written tests, coverage-feedback agents) verifies test effectiveness with deterministic
  tooling, never with the model judging its own work.
- **A custom AST/trace-based function-coverage generator.** Rejected as unnecessary: coverage.py
  7.6+ reports per-function coverage in its JSON output, and function coverage is a standard
  first-class metric in other ecosystems (Istanbul/Jest). Line/branch percent reports do not
  identify uncovered functions directly.
- **A percent gate on lines or changed lines (diff-cover style) as the whole check.** Rejected:
  percent gates cannot judge assertions, mocks, range boundaries or test structure; the draft
  requires rule-level review of exactly those, on a machine-measured basis.
- **Mutation testing as the strength metric.** Rejected: it is expensive (a suite run per mutant),
  needs per-language tooling and produces noise; not required by the conventions. Possible future
  extension.
- **Encoding repository-specific mock practices into the prompt.** Rejected: the review must be
  project-independent; conflicts with repository rules are resolved in favor of the repository,
  and deviations from the conventions remain errors under the conventions.
- **Regenerating the reports on every loop iteration regardless of changes.** Rejected: repeated
  generation without code changes wastes runs; the report is produced once after the task and
  again only after fixes.

## Consequences

- Positive: executor-written tests become a first-class reviewed artifact — a run now proves that
  the changed code is actually executed by tests at the function level, in the diff's scope.
- Positive: the project's test process becomes machine-measurable: coverage and latency report
  generation become part of it (created in this task for this repository, reusable by later runs).
- Positive: no new mechanism is introduced — the kind slots into the existing parallel-loop
  structure (registry, sessions, merged report, common fix pass).
- Positive: the deterministic evidence base keeps the review honest, and a language without
  function-coverage tooling degrades to a PASS with a warning rather than an unresolvable FIX.
- Negative: every task run pays at least one test-suite run with report generation, and every
  fix iteration pays again when code changed.
- Negative: tasks in projects without report tooling grow in scope — the executor must first
  build the generators.
- Negative: an unrelated failing or flaky suite can produce false FIX findings for the change
  under review.
- Negative: every consumer of the kind registry must be extended in lockstep, and the user-facing
  pipeline descriptions (the README step lists) must be updated.

## Acceptance Criteria

- Both pipelines run the tests check as the fifth kind inside the unified parallel review-fix
  loop: it merges into the common review report, is fixed in the common fix pass, reruns only
  while failing, and shares the iteration cap; the review pipeline applies it to the branch-diff
  scope as well.
- The tests check runs in a dedicated reviewer role in its own fresh session on the planner's
  model and produces a report whose first line is exactly `TESTS: PASS` or `TESTS: FIX`, with
  findings in the prescribed format and latency as `NOTE:` remarks only.
- The verdict is grounded in machine-produced function-level coverage and latency reports from
  the project's test process: the reports exist when the check starts (generated by the executor
  as part of the task) or the reviewer runs the project's generator itself; reports are not
  regenerated while the code is unchanged.
- The check covers only tests for the executor-changed code (the diff, untracked files included)
  and enforces: 100% function-call coverage of the changed public API; module-level tests for
  added or extended internal-API behavior; no private-member access from tests; min/max/mid
  coverage with asserted results and no exhaustive enumeration; the mock policy (allowed reasons
  only, state recorded from the real service); tests located in their module's own test scope;
  failing tests reported as a blocking finding.
- In this repository, the test process can produce the function-level coverage and latency
  reports the check requires, so the stage can pass in the project's own runs.
- A project whose language lacks function-coverage tooling — verified, not assumed — receives a
  PASS with a warning, not a demand for fixes.
