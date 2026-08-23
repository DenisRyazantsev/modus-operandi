---
slug: dedicated-reviewer-sessions
status: accepted
date: 2026-08-23
---

# ADR-0017: Dedicated Reviewer Roles Reviewing in Their Own Fresh Sessions

## Context

The review loops (ADR-0009, ADR-0013) ran each check kind (`srp`, `bugs`,
`review`, `comment`) as a **fork of the warm planner session** under the
planner role. Consequences: the reviewer inherited the planner's entire
history (planning reasoning, old decisions) as noise, the review rules had
to be carried by the step prompts because there was no reviewer identity,
and the planner agent's description still advertised review duties. The
user requires: dedicated reviewer agents that review the code in their own
**fresh** sessions — never in a fork of the planner session — and that
review on the same model as planning (reviews are an analysis task of the
same difficulty as planning, so the cheap executor model must not be used
for them).

## Decision

1. **Dedicated reviewer roles.** Four reviewer agents — `reviewer-srp`,
   `reviewer-bugs`, `reviewer-review`, `reviewer-comment` — one per review
   kind, each with its own role body carrying its review rules and verdict
   markers. The planner agent is no longer described as a reviewer.
2. **Fresh per-kind sessions.** The first check of a kind starts a brand-new
   session that receives only the plan and the ADR (via the step prompt) —
   it inherits no context from the planner or any other agent. Every later
   check of the same kind continues that same session, so the reviewer keeps
   its past findings across the review-fix-loop iterations. A vanished
   session (backend cleanup) is dropped and restarted fresh; the planner's
   warm session is never touched.
3. **Planner model.** All reviewer roles run on the planner's model on both
   backends (opencode agents render with the planner model; the cursor
   backend passes the planner model slug and prefixes the reviewer role
   body).
4. **No warm-up step.** The workflow's planner warm-up step is removed: the
   review pipeline starts with scope determination and goes straight into
   the parallel review fan-out.
5. **Backward-compatible log parsing.** The old `-fork-<kind>` log marker
   from planner review forks is still recognized so stale log files from an
   older install keep working; the reviewer logs themselves are stable
   per-kind files named after the role.

## Alternatives

- **Keep forking the warm planner session (status quo, ADR-0013).**
  Rejected: the reviewer's context is the plan and the ADR, which the step
  prompt references anyway — inheriting the planner's history adds only
  noise and stale decisions, and a forked session dies with the parent.
- **Reviewer on the executor model.** Rejected: reviewing is an analysis
  task of the same difficulty as planning; the cheap executor model is
  reserved for implementation.
- **A single reviewer role for all kinds.** Rejected: the four review kinds
  have different rules and verdict markers, and per-kind sessions let each
  reviewer remember its own past findings.
- **Warm the reviewers in a separate step.** Rejected: a fresh session
  started on demand is already the minimal context the review needs.

## Consequences

- Positive: reviews start from a clean, minimal context (plan + ADR) and
  keep their findings across iterations; the review rules move out of the
  step prompts into the reviewer role bodies, which the verdict gate
  matches; reviewer sessions are independent of the planner session's
  lifetime.
- Positive: the review pipeline loses the warm-up step.
- Negative: a per-kind session's context grows with the fix-loop iterations
  (bounded by the maximum fix-iteration cap); a reviewer's first check
  re-reads the scope from scratch.
- Partially supersedes ADR-0013 (per-kind forks of the planner session);
  the live-log label `[reviewer-<kind>]` joins the role column (ADR-0016).

## Acceptance Criteria

- Each review kind runs in its own dedicated role's fresh session, created
  on first use and reused across the loop iterations; a lost session is
  restarted fresh and the planner's session is never mutated.
- The reviewer roles run on the planner's model on both backends.
- The review pipeline has no planner warm-up step.
