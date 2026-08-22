---
slug: executor-output-limit-implement-check
status: accepted
date: 2026-08-15
---

# ADR-0006: Executor Output Limit (`OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`) and Implementation Check After `implement`

## Context

In a pipeline run, the `implement` step did not make a single change to the repository: the executor read the task
brief, exhausted its entire output budget on reasoning, and finished without doing the work — no tool calls at all.
The cause is an opencode internal limit: opencode caps per-step output at 32 000 tokens regardless of provider
capabilities (the provider supports far more output with a large context). The configured output limit does not affect
this cap; the only way to raise it is the `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` environment variable.

The empty implementation was not detected in time: the review steps passed vacuously over an empty diff, and only a
later review loop caught that the feature was not implemented at all, making the executor redo the work. The pipeline
needs an early, cheap guard against the "executor did not do the work" scenario.

## Decision

Raise the opencode per-step output cap by exporting `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=1000000` (1M tokens)
before launching opencode for pipeline steps. The value is a practical "no cap": the actual per-response budget
remains bounded by the provider, so opencode stops truncating requests before the API does. The variable applies to
both roles (planner and executor) and only removes the upper bound — it does not force the model to spend more.

Add an implementation check immediately after the `implement` step, before any review runs: the check passes if
tracked files changed or new non-ignored files appeared; workflow and state directories do not count as changes. If
there are no changes, the executor is called again in the same warm session with a short "you didn't do changes"
message, and the check runs again. If there are still no changes, the pipeline fails with a clear error explaining
that the executor did not change the repository in two attempts (likely causes: response cut off by the limit, a
hang, or misunderstanding of the task), pointing to the session log and how to continue (the resume command). The
check is structured as a bounded check-and-retry loop in the same style as the existing loop steps.

## Alternatives

- **Trust the existing review loop (it catches "nothing implemented").** Rejected: it triggers late — before it, the
  earlier review stages run idle over an empty diff; an empty implementation should be detected right after
  `implement`, not after several agent runs.
- **Check only for modifications of tracked files, without accounting for new files.** Rejected: a new feature may
  consist entirely of new files, and a diff-only check would miss it.
- **Retry unboundedly or rely only on manual resume.** Rejected: unbounded retry risks endless cost; manual resume
  remains the fallback path after two attempts.
- **Allow a "legitimately empty" implementation.** Rejected: the pipeline is for features that change code; if a
  feature requires no repository changes, such a run should not start.

## Consequences

- Positive: an executor cut off by the reasoning limit no longer results in an empty implementation — opencode does
  not truncate requests before the provider does.
- Positive: an empty implementation is detected right after `implement` (seconds instead of several agent runs), so
  the intermediate review stages are not wasted on an empty diff.
- Positive: the retry goes through the warm session — the task context is preserved and the retry message is cheap.
- Negative: the 1M-token cap raises the maximum possible token spend per single response; actual spend is still
  bounded by the provider and the remaining context.
- Negative: `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` is an experimental opencode mechanism; behavior may change on
  update (in a future opencode version the cap is removed and the limit goes into the request as-is).
- Negative: re-invoking the executor on an empty implementation adds time and tokens to the run (bounded to two
  attempts).

## Acceptance Criteria

- The executor's per-step output budget is not truncated by opencode before the provider limit.
- After the implementation step, the pipeline verifies the repository actually changed, retries once in the same warm
  session, and fails with a clear error and resume hint otherwise.
