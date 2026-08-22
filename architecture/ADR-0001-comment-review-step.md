---
slug: comment-review-step
status: proposed
---

# ADR-0001: Code Readability Review Step (Why-Comments) After the Review → Fix Loop

## Context

The pipeline runs a review → fix loop after implementation that checks the code against the ADR and fixes found
defects. However, even after bugs are fixed, the code still contains places that are correct but non-obvious: a
future reader (a senior developer opening the file for the first time) may make a wrong assumption about what the
code does and why it was written that way.

This is not about finding errors, but about "comprehension traps": magic numbers with no visible origin,
workarounds and hacks, non-standard API usage, deliberately swallowed exceptions, edge cases, business rules inside
conditions, implicit invariants, odd optimizations, and conscious technical debt. All of these are candidates for an
explanatory comment about the reason (`why`), not about what the code does (`what`).

## Decision

Add a separate code readability review step (`comment-review`) after the review → fix loop. Its task is to find
only places that mislead the reader — not bugs. The reviewer runs in the same session and context as the other
steps to save tokens; no separate fresh context is created.

The reviewer follows strict rules:

- Comment only on `why`, never on `what`; apply the Chesterton's fence test; suggest a rename or refactoring
  instead of a comment when that is the better cure; evaluate relative to the typical reader of the codebase.
- Check the non-obviousness triggers in order: magic numbers/constants, workarounds/hacks, non-standard API,
  swallowed exceptions, edge cases, business rules in conditions, implicit invariants, odd optimizations, external
  constraints, known limitations/technical debt.
- Return an empty list when there are no findings — noise is worse than silence.
- Produce a strictly structured result without preamble: for each finding the location, one sentence on why a
  reader would be misled, a 1–2 line comment (WHY only, in the language of the codebase's commits), and a verdict
  of `COMMENT` or `REFACTOR`.

The step closes into a `comment-review → fix` loop (similar to the existing loops) with an iteration cap and a
final passing verdict; found comments are applied to the code.

## Alternatives

* **Do not add a separate step; extend the existing review → fix loop.** Rejected: mixes two different goals
  (correctness and readability), complicates the prompt, and blurs the pass/fix criteria.
* **Add comments directly during implementation.** Rejected: the code author is "blind" to their own non-obvious
  places; a separate review stage is needed, not edits during writing.
* **Use a third-party tool (linter/doc generator) instead of an LLM reviewer.** Rejected: such tools do not
  capture the "why" semantics — only "what", which is explicitly forbidden by the rules.
* **Do the readability review manually without automation.** Rejected: contradicts the pipeline's goal of
  automating the whole chain.

## Consequences

* Positive: code gets only meaningful comments about the reasons behind decisions, not obvious descriptions; the
  risk of erroneous changes caused by future readers misunderstanding context decreases.
* Positive: the "noise is worse than silence" rule and the ban on `what`-comments minimize codebase clutter.
* Negative: one more LLM step and fix loop increase pipeline runtime and cost.

## Acceptance Criteria

* After the review → fix loop, a readability review step runs that checks only the listed non-obviousness triggers
  and reports no findings when there are none.
* The review produces a strictly structured result without preamble: for each finding a location, one sentence on
  why a reader would be misled, a 1–2 line WHY-only comment in the language of the codebase's commits, and a
  verdict of `COMMENT` or `REFACTOR`.
* On a `FIX` verdict, a fix step applies the comments from the latest review and the loop repeats until `PASS`;
  the number of iterations is capped by a setting, as in the existing loops.
* Comments are added only about the reason (`why`); `REFACTOR` recommendations are implemented as a rename or
  refactoring, not as a comment.
* The step runs in the same session and context as the other pipeline steps.
