---
slug: task-pipeline
status: accepted
date: 2026-08-17
---

# New `task` Pipeline: Motivation → Research → Proposal → Approval → ADR Without a Second Gate

## Context

There are currently two pipelines: `adr-pipeline` (a human formulates a feature → the planner writes an ADR →
approve/revise/reject gate → executor questions → implementation → review-fix loop) and `review-pipeline` (review
only). The `adr-pipeline` entry point immediately writes an ADR from the raw formulation: the task motivation is not
clarified, no research is done, and the human sees the chosen solution and its pros and cons only inside the ADR at
the gate.

A third `task` pipeline is needed where the human formulates a task and the LLM, before writing the ADR, goes
through phases: (1) study the project and understand the motivation — if unclear, ask motivation questions in a loop
of at most 3 rounds; (2) research how such a task is usually solved and produce a proposal with pros and cons; (3)
show the proposal to the human, get comments, revise, show again — at most 3 rounds; (4) after approval, write the
ADR and continue along the existing adr pipeline, but the executor's questions are also a loop: after the planner's
answers the executor decides whether it understood everything, and if the answers spawn new questions it asks again —
at most 3 rounds. There is no separate ADR approval: approval already happened at the proposal stage.

## Decision

A separate workflow `task-pipeline` is added rather than modifying `adr-pipeline`.

1. **Inputs and roles.** Inputs: `task` (required), optional task id, state directory, adr directory,
   `motivation_verdict`, and `proposal_verdict`. All task phases are executed by the planner in one warm session, so
   the study → proposal → ADR context is kept together; the executor connects only at the question stage.

2. **Motivation phase.** The planner studies the project and writes a study document — project understanding,
   reformulated task, assumed motivation, and numbered open questions. A human gate offers `clear`/`clarify` (no
   reject choice by design — the real approval point is the proposal gate); on `clarify`, the human writes feedback
   and the planner revises the study. The loop exits on `clear` or after 3 rounds, without a final gate.

3. **Research phase.** The planner researches how such a task is usually solved (web search) and writes a proposal
   document with sections: motivation, proposed solution, pros, cons, considered alternatives, implementation plan,
   and source references. This is the document shown to the human.

4. **Proposal approval loop.** A human gate offers `approve`/`revise`/`reject`; on `revise`, the human writes
   feedback and the planner revises the proposal. The loop exits on approval or after 3 rounds; an unapproved
   proposal does not become an ADR (a final approve/abort gate fires when rounds are exhausted without approval).

5. **ADR without separate approval.** The planner writes the ADR in the standard format from the study document and
   the approved proposal, and the ADR is released immediately — there is no `adr-loop`/ADR gate, because approval
   already happened at the proposal stage.

6. **Executor question loop.** The existing one-shot executor-questions/planner-answers pair is replaced by a loop:
   the executor writes all remaining open questions (unresolved from previous rounds plus new ones arising from the
   answers); if no questions remain it signals completion; otherwise the planner answers them all line by line. The
   loop exits when no questions remain or after 3 rounds; the pipeline then continues with implementation, with
   deviations from the plan recorded as before. The rest of the tail (implementation, review-fix loop, adr sync,
   pass check) matches `adr-pipeline`. The YAML duplication is deliberate: the engine has no workflow import or
   chaining, and two separate runs would break the warm sessions.

7. **Infrastructure.** New prompts for the task phases (study, research, proposal revision, ADR writing) and an
   updated executor-questions prompt that re-reads the previous round's answers; the planner-answers prompt is
   unchanged. A new script checks whether questions remain. Three config iteration caps, each defaulting to 3,
   govern the motivation, proposal, and question loops. When human gates are disabled, the two verdict inputs are
   omitted and both gates auto-pass by default. A `task` subcommand is added to the launcher so the pipeline starts
   with `modus-operandi task "<description>"`.

## Alternatives

- **Extend `adr-pipeline` with an optional prefix under a flag.** Rejected: conditionally skipping the ADR gate
  complicates the step graph and verdict plumbing and blurs the existing pipeline's semantics.
- **Two sequential runs (task phases, then adr-pipeline with the same task id).** Rejected: two commands instead of
  one, sessions between separate runs are not guaranteed warm, and the second run would reopen the ADR gate.
- **The executor runs research and the proposal.** Rejected: a cheap model for research and planning lowers quality,
  and the planner session that wrote the proposal immediately writes the ADR without context handover.
- **Only the LLM assesses motivation, without a human gate.** Rejected: human confirmation of clarity matches the
  existing gate UX and requires no new mechanics.
- **One-shot executor questions, as in adr-pipeline (status quo).** Rejected: questions arising from the planner's
  answers would remain unanswered until the implementation stage — exactly what the question loop eliminates.

## Consequences

- One run and one pair of warm sessions cover the whole path from task to review; motivation is clarified before
  research, the proposal is approved before the ADR, and there is no double approval (proposal + ADR); executor
  questions are closed before implementation instead of surfacing at the code stage; all existing infrastructure is
  reused — gates, feedback editing, ADR release, review loops, the wrapper, and statistics.
- Human touch points remain only at the motivation and proposal gates; with human gates disabled both loops
  auto-pass and the pipeline runs without a human.
- The adr-pipeline tail is duplicated in the new workflow and deliberately diverges in the question step (loop vs
  one-shot round) — tests control the synchronization of the remaining steps and the divergence itself; the
  study/research phases make the run longer; the research phase depends on the planner having web tools; the
  question loop adds up to two extra planning rounds when answers spawn new questions.

## Acceptance Criteria

- The task pipeline moves from motivation (with up to 3 clarify rounds) through research and an approved proposal
  to the ADR — with no second approval gate; an unapproved proposal does not become an ADR.
- Executor questions are closed in up to 3 rounds before implementation: remaining questions and new ones arising
  from the planner's answers are re-asked until none remain, and the pipeline then continues with implementation
  without a gate.
- With human gates disabled, both the motivation and proposal gates auto-pass by default and the whole pipeline
  runs unattended.
- The planner executes all task phases in one warm session; the executor connects only at the question stage.
- The config exposes the three iteration caps (motivation, proposal, questions), each defaulting to 3; the new
  `modus-operandi task "<description>"` command starts the pipeline; existing pipelines are unaffected.
