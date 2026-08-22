Read @STATE_DIR@/tasks/current/study.md and the approved @STATE_DIR@/tasks/current/proposal.md, then write the ADR into @STATE_DIR@/tasks/current/adr.md. The frontmatter MUST include a slug field: a short 2-3 word summary of the ADR in ENGLISH, lowercase kebab-case.

The skill about how to write ADR:

## What an ADR is

An ADR is a short, historical document that records an **architecture decision**: the context that forced it, the
problem being solved, the options that were evaluated, and what was chosen — with the reasoning.

An ADR answers exactly two questions:

1. **WHAT** was decided?
2. **WHY** was it decided — and why not the alternatives?

An ADR captures the motivation, the trade-offs, and the history of a choice so that future readers can understand
it and so that the decision does not have to be re-litigated.

An ADR is **NOT**:

- an implementation plan or a how-to guide;
- a task description, ticket, or todo list;
- a changelog or release notes;
- a code review.

## The line between ADR and implementation

The ADR describes the **decision space**: the problem, the forces, the options, the choice, the consequences.

The implementation describes the **solution space**: what files to touch, what to rename, what functions to add,
what lines to write, how the code will be structured.

Implementation details belong in the implementation — a task description, an issue, or the code itself. They do
**not** belong in an ADR.

## Template

Use the following template when creating a new ADR. Fill in all sections.

The title starts with `ADR-NNNN` where `NNNN` is the next sequential number for the project.

```markdown
---
slug: <short-kebab-case-slug>
status: proposed
date: YYYY-MM-DD
---

# ADR-NNNN: <short title: the problem and the chosen solution>

## Context

<The situation that motivated the decision. What was the problem? What forces
(constraints, trade-offs, user requirements, observed failures) made the status quo
unacceptable? Describe the problem, not the intended fix. 2-5 sentences.>

## Decision

<What was decided. State the chosen solution and the reasoning: which forces it
resolves and why it is the best option. Focus on WHAT and WHY — not on how to build it.>

## Alternatives

<Options that were considered and rejected, each with the reason for rejection.>

## Consequences

- <positive consequence>
- <negative consequence>

## Acceptance Criteria (optional)

<Outcome-level, verifiable criteria that confirm the decision was implemented as
decided. State outcomes, not file-level change lists.>
```

## Rules

1. Be as concise as possible.
2. Write the **decision**, not the implementation:
   - describe the context, the problem, the considered options, and the reasoning for the choice;
   - never describe HOW to implement the solution;
   - no instructions like "add line Y to file X so class Z can do U";
   - no file-level change lists, step-by-step how-to guides, function/class/line-level descriptions, or code
     snippets that prescribe the implementation.
3. Do not mention concrete file names, classes, functions, or exact commands — **unless the artifact itself is the
   decision** (e.g., choosing a library, a protocol, a tool, a package name).
4. Write for a reader who has only this ADR and wants to understand the choice — not for the engineer who will
   implement it.
5. Acceptance Criteria, when present, are **outcome-level**: "the CLI supports subcommands X, Y, Z" or "an update
   must not overwrite a user-modified config" — never "in file X change line Y".

## Self-check before writing

Ask yourself:

- Does this section explain the **problem and the reasoning**?
- Would a reader who never opens the codebase understand the decision and its motivation from this ADR alone?

