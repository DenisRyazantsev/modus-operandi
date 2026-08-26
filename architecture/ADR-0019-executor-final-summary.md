---
slug: executor-final-summary
status: accepted
date: 2026-08-26
---

# ADR-0019: Executor-Written Summary of What Was Done at the End of Both Pipelines

## Context

A pipeline run ends abruptly for the user: after the review loop converges, the run saves the ADR, prints the review verdicts and the statistics block — but never answers the question "what was actually done?". Reconstructing this requires reading the ADR, the plan and the git diff by hand. The executor is the only agent that knows what it really did (deviations from the plan, unexpected discoveries, review-fix iterations), and its warm session is available at the end of the run for free. The plan-and-execute literature treats the final synthesis pass as a mandatory stage and names its absence an anti-pattern ("skipping synthesis — dumping step outputs without a final coherence pass produces fragmented answers").

## Decision

Both workflows (task and review) gain a final step, the very last step of the run: the executor, in its warm session, writes a high-level summary of what was ultimately done — the essence of the changes grouped by logical area (not a per-file listing), any deviations from the plan, how the work was verified, and the outcome of the review findings. The summary document is written by the executor itself (not derived by scripts or by the planner), saved as a permanent artifact in the task's artifact directory, and displayed to the user at the end of the run. The executor-facing prompt and the summary are in English, the pipeline's working language.

The summary is advisory: it never gates anything and never fails the run. A missing summary document is treated as unexpected behavior and reported as a warning, not an error — the run result (including its exit code) is already determined by then. This mirrors the established practice in agent workflows that final reports are user-facing, correctable on read, and not worth an expensive review pass.

## Alternatives

- **No summary (status quo).** Rejected: the run ends without a coherent answer to "what was done" — the exact anti-pattern the synthesis stage exists to avoid.
- **A deterministic script generating the summary from the git diff.** Rejected: it produces a change listing without narrative, reasoning, deviations or insights; the requirement is a summary from the executor agent.
- **The planner writes the summary.** Rejected: the planner does not know what was actually done (execution details, deviations); it runs on the expensive model and writing the summary would break the role separation — the executor is the one who executed.
- **A dedicated fresh summary session.** Rejected: it would have to reconstruct the execution context from artifacts; the warm executor session is cheaper and more accurate.
- **Concatenating step outputs into a report.** Rejected: fragmented step dumps without a coherence pass — the documented anti-pattern.
- **Reusing the review report as the summary.** Rejected: the review report is a findings document written by the reviewers, not an account of what was done.

## Consequences

- Positive: the user gets a human-readable account of what was done at the very end of the run, in both pipelines, without reading plans and diffs; the summary doubles as the basis for a commit message or release notes.
- Positive: the summary is written by the only agent with full knowledge of the execution (including deviations and review iterations), at the cost of one extra step in an already-warm cheap session.
- Positive: the run outcome is never affected by the summary — a missing or imperfect summary degrades to a warning.
- Negative: every run pays a small extra agent step (time and tokens); a lost warm session makes the step start cold, so the prompt must let the executor ground itself in the task artifacts.
- Negative: a model-written report can contain inaccuracies or misattributed decisions; being advisory and high-level keeps this user-facing and cheap to correct.
- Negative: both workflows and their structural tests gain one more step to keep in sync.

## Acceptance Criteria

- Both the task and the review pipeline end with a summary step as their last step, after the final pass check.
- The summary is written by the executor agent in its warm session and displayed to the user at the end of the run.
- The summary is high-level: grouped changes with the essence of what was done, deviations from the plan (if any), how the work was verified, and the review outcome — not a per-file change listing.
- A missing summary document does not fail the run; it is reported as a warning about unexpected behavior.
- The summary is persisted as a permanent artifact in the task's artifact directory, alongside the other task artifacts.
