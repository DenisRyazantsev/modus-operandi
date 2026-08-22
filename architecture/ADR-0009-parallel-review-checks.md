---
slug: parallel-review-checks
status: accepted
date: 2026-08-16
---

# Parallel Execution of Both Pipelines' Checks via Warm-Session Forks + Stage Latency Table

## Context

Both pipelines — `adr-pipeline` and `review-pipeline` — run four review checks (SRP, bugs, review, comment) strictly
sequentially, each in its own loop of review → verdict → fix → pass-check. All steps resume the same warm planner
session, so each next check waits for the previous one and mutates the shared session. This yields the summed
wall-clock time of all four loops and spreads the findings across four separate executor fixes.

Established facts:

- The workflow engine executes top-level steps sequentially; parallelism is only available via fan-out
  (`max_concurrency > 1`) plus fan-in (`wait_for`).
- `opencode run --fork` creates an isolated fork of a warm session and runs the prompt in it without touching the
  parent session.
- The checks differ per kind in their review prompt, report file prefix, and PASS marker, but share the same
  verdict mechanics: a report file whose first line must equal the kind's PASS marker.
- A snapshot mechanism captures the code state before a check so re-reviews see the diff after the fix.
- Final statistics are already printed without a per-stage breakdown; the engine's step results carry no timestamps,
  so stage latency must be measured in the wrapper layer, which already observes the step lifecycle.

The goal is to parallelize the four checks in both pipelines, isolating each in a fork of the warm session, collect
all findings into a single document, hand them to the executor in one pass, restart only the failed checks until all
pass, and finally print a per-stage latency table.

## Decision

1. **One warm session, forks per check.** A warm planner session is created/resumed once before the checks (in
   `adr-pipeline` it is the already warmed planning session; in `review-pipeline` an explicit warm-up step is added).
   Each of the four checks then runs in a fork of this session, inheriting the warm context while remaining isolated.
   This eliminates races between parallel checks over one session.

2. **Parallel execution.** In both pipelines, the four sequential check loops are replaced with one outer retry loop
   inside which a fan-out with `max_concurrency: 4` runs all four checks concurrently over the list of check kinds.
   Each check writes its own report with a verdict first line, as today.

3. **Merging reports.** After the checks, the four latest reports are deterministically merged into one document
   `review-report.md` with per-kind sections, preserving all findings (concatenation with headings, not a synthesized
   summary). This document is the executor's only input.

4. **One fix pass.** The executor fixes all findings in one pass with a single common prompt reading the merged
   report, without per-type separation; the per-type fix prompts are no longer invoked.

5. **Restart only the failed ones.** After the fix, verdicts are recomputed per kind; on the next retry-loop
   iteration, only the kinds whose latest report lacks the PASS marker are re-run. The loop repeats (check → merge →
   fix) until all four kinds pass or the iteration cap is exhausted.

6. **Final verdict.** The overall run passes only if all four latest reports carry their PASS markers; on cap
   exhaustion the run ends with a warning. A single retry-loop cap from the config replaces the four per-check caps;
   the old per-check config keys remain for backward compatibility but no longer govern separate loops.

7. **Per-stage latency table.** The wrapper records each stage's start and end and, on completion, prints a latency
   table in the final statistics block: one row per stage (name → duration), plus a breakdown of what the time was
   spent on (agent model calls vs shell overhead; for the parallel checks — each check's duration and the fan-out's
   total wall time). Measurement happens in the wrapper layer, which already observes the step lifecycle.

## Alternatives

- **Keep sequential (status quo).** Rejected: summed wall-clock time, a shared mutated session, and four separate
  fixes — exactly what needs to be eliminated.
- **Parallel, but fresh sessions without forks.** Rejected: the warm context is lost, each check re-reads the
  scope and code (higher token spend), and parallel checks without session isolation would race over a shared id.
- **Parallel with forks, but per-type fixes.** Rejected: contradicts the requirement of one common fix prompt
  without type separation.
- **Agent synthesis of the merged report.** Rejected for the executor's input: synthesis may lose findings; the fix
  needs the full, deterministic list.
- **Measuring latency inside the workflow's shell steps.** Rejected: engine steps do not equal stages (four parallel
  checks form one fan-out step but four stages), and step results carry no timestamps; measuring in the wrapper gives
  whole stages without scaffolding in every step.

## Consequences

- Wall-clock drops from the sum of four loops to the maximum of one check plus the fix; forks isolate the checks
  from each other and do not pollute the parent warm session; the executor sees all findings at once and fixes them
  in one pass.
- Restarting only the failed checks does not waste time and tokens on already-passed ones; the latency table shows
  which stage consumes the time.
- Four forks duplicate scope reading relative to an ideal shared context (though cheaper than four fresh sessions);
  parallel calls hit the provider's rate limits harder than sequential ones.
- Deterministic concatenation is bulkier than an agent summary; the snapshot mechanism must be aligned with the new
  loop structure so re-review prompts correctly see the diff after the common fix; latency measurement adds
  scaffolding to the wrapper (without changing failure behavior — statistics degrade to zeros, as now).

## Acceptance Criteria

- The four review checks (SRP, bugs, review, comment) run in parallel in both `adr-pipeline` and `review-pipeline`,
  each isolated in a fork of the warm planner session; there are no longer four sequential check loops in either
  workflow.
- Findings from all checks are merged into one document and fixed by the executor in a single pass with one common
  prompt.
- Only the failed checks restart after a fix; the run ends when all four checks pass or the iteration cap is hit
  (with a warning).
- A per-stage latency table is printed at the end, with a breakdown of where the time was spent; when data is
  missing, statistics degrade to zeros and do not break the run.
