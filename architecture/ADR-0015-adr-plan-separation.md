---
slug: adr-plan-separation
status: accepted
date: 2026-08-22
---

# ADR-0015: Separate the ADR from the implementation plan

## Context

The project uses the word "ADR" for two distinct entities merged into a
single task artifact: a record of an architectural decision (context,
motivation, options, choice, consequences — for humans) and an
implementation plan (the details of "how" — for the executor). This
produces contradictory planner instructions ("the ADR must not contain
implementation details" vs. "specific enough for a cheap model to implement
without re-asking"), which is why published decision records swell into
step-by-step manuals with file names and commands, while the executor has
to work from a document that is forbidden to contain such details. Human
requirements: the plan is executor-only, a channel for the strong model's
insights; the ADR is a living artifact of the whole run, published in its
final form; when deviating from the plan the executor must not re-read the
whole plan (agent sessions are warm); the research proposal document lost
its purpose after the human approval gate was removed. Established
practice agrees: AWS — "Separate design from decision", Microsoft — "Avoid
making decision records design guides", MADR — the Mega-ADR antipattern is
cured by moving detailed design into a separate document.

## Decision

We separate the two entities into two independent artifacts written by the
planner:

1. **ADR** — the architectural decision record for humans and the executor
   (what/why): context, considered options, the choice with its rationale,
   expected consequences, outcome-level acceptance criteria. No
   implementation details (file names, functions, step-by-step
   instructions) — except when the artifact itself is the subject of the
   decision. A living draft for the whole run; only the final version is
   published to the public decisions directory at the end of the run.
2. **Implementation plan** — executor-only (how): the concrete changes,
   the order of work, verification criteria. Not published, not shown to
   humans at gates, has no number or status.

Order: the ADR is written right after the research, the plan right after
the ADR; the executor implements per the plan (the ADR as decision
context) and asks clarifying questions about both documents. The research
result is kept as a separate artifact — the planner's material; the
proposal document is abolished. Reviews compare the code only against the
ADR's acceptance criteria: the plan is a "soft" document, deviating from
it while the ADR criteria hold is not a violation.

If the executor cannot follow the plan, it records a **plan amendment**
(why the plan does not work, what insights were gained, a proposal for
next steps); the planner agrees to it and rewrites the ADR if needed;
after the agreement the executor continues implementing without re-reading
the whole plan. No separate deviation records or ADR amendment sections
are created.

Existing published decision records stay unchanged: this is an append-only
history.

The choice is justified because it removes the instruction contradiction
(the ADR is strictly what/why, the plan is the single place for "how"),
keeps the public decisions log clean, gives the executor a detailed
how-document not bound by ADR rules, and follows the common practice of
separating the decision from the design, including the spec-kit engine's
own scheme (spec → plan → tasks).

## Alternatives

- **Status quo** (one document with a dual purpose). Rejected: that is
  the problem being solved.
- **One file, two sections** (a plan section inside the ADR, cut off at
  publication). Rejected: details could still leak into the public log,
  publication filtering is fragile, and the task requires separating the
  entities.
- **Three artifacts** (the full spec-kit chain: ADR + plan + individual
  tasks with phases). Rejected: the executor is a single LLM session, not
  a per-task runner; two artifacts are enough.
- **The plan as a section of the research document.** Rejected: the
  research artifact is abolished, and the plan must stay an
  executor-only document.
- **"Expected Implementation Touchpoints" inside the ADR** (Gordon
  Beeming). Rejected: the task explicitly forbids implementation details
  in the ADR; the "how" need is covered by a separate plan.
- **The executor writes the plan itself.** Rejected: planning on a strong
  model is the essence of the planner → executor pipeline.
- **Publishing the ADR at the start of the run plus amendment sections
  after deviations.** Rejected by the human: the ADR is an artifact of the
  whole run, published once, in its final version.
- **Intermediate draft publication with a `-draft` suffix.** Deferred: the
  draft lives only in the task directory anyway; revisit if an early
  number reservation becomes necessary.
- **A human gate for plan approval.** Rejected by the human: the plan is
  an internal executor-only document.

## Consequences

- Positive: the public decisions log consists of short readable records
  that do not go stale on refactoring.
- Positive: the planner's instruction contradiction disappears; the "how"
  details live in the single allowed place — the plan.
- Positive: the executor gets a detailed specification free of ADR rules;
  the strong model's insights reach the weak one without loss.
- Positive: deviations from the plan are agreed before the ADR is
  published, so the decision record is final from the start and needs no
  amendments.
- Negative: an extra artifact and an extra planning stage — the run costs
  more in tokens and time.
- Negative: the two documents can drift apart (the risk is mitigated by
  the plan being written after the ADR, and the ADR being the only source
  of truth for reviews).
- Negative: ADR publication is deferred to the end of the run — an
  interrupted run leaves no record in the log.
- Negative: historical records remain "mixed" — a conscious
  inconsistency in the history.

## Acceptance Criteria

1. After the planning stage a task has two distinct artifacts: a decision
   record (only what/why, outcome-level acceptance criteria, no file or
   function names, no step-by-step instructions) and an implementation
   plan (concrete changes, order, verification criteria).
2. The plan is consumed only by the executor, never published to the
   accepted-decisions directory and never shown to humans at gates.
3. The executor implements per the plan, reading the decision record as
   context; it asks questions about both documents.
4. Reviews compare the code only against the decision record's acceptance
   criteria; deviating from the plan while those criteria hold is not
   recorded as a violation.
5. When it cannot follow the plan, the executor records an amendment; the
   planner agrees to it (supplements the plan and, if the decision itself
   changed, rewrites the decision record), after which the executor
   continues implementing without re-reading the whole plan; no separate
   deviation records or amendment sections appear.
6. The decision record is published to the accepted-decisions directory
   once, at the end of the run, in its final version, including the
   changes made after agreements.
7. Research produces no proposal document: its result is available to the
   planner as a separate artifact, and the human motivation document does
   not depend on it.
8. Previously published decision records are not modified.
9. A task-pipeline run completes successfully; the project's existing
   tests and linter pass.
