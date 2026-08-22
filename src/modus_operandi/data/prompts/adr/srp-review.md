Review the executor's changes for SRP violations ONLY. Do NOT review bugs,
correctness, acceptance criteria, or comment quality (other stages do that).

The diff is only a marker: it tells you WHICH files the executor touched, not
what to review. Run git status, then git diff HEAD (git diff does not show
untracked files, so new files made by the executor appear only in git status —
include them in the review scope). Collect every file that was created or
modified by the executor's work, then review each of those files IN FULL, as
it exists now — not just the added lines.

Skip files with fewer than 300 lines of code — this is a scope filter to keep
the review fast, not an SRP criterion. A skipped small file can still violate
SRP; the filter just accepts that risk for speed.

For each remaining file, the question is: does this file have exactly one
responsibility — one reason to change? Check for:

- Multiple classes in one file — split them (project style: one class per
  file). This is the floor, not the whole check: a file with one class or no
  classes can still violate SRP.
- God classes: a single class mixing unrelated concerns (e.g. I/O + parsing +
  state + rendering + statistics). Split by concern.
- God functions: a function doing many steps at mixed abstraction levels —
  extract helper functions.
- Classless procedural files: still must be cohesive. A file mixing unrelated
  concerns (e.g. CLI parsing + orchestration + file I/O + output formatting)
  is an SRP violation even with zero classes.
- Mixed abstraction levels: low-level operations inlined next to high-level
  orchestration.

A big file is suspect but a file that does one thing well is fine regardless
of size. However: the executor just added code to this file — if the file is
already large and mixing concerns, this is exactly the moment to split it, and
do not grow a new concern inside an existing monolith.

Write @STATE_DIR@/tasks/current/srp-review-@N@.md with the first line exactly
'SRP: PASS' or 'SRP: FIX' followed by actionable findings. Each finding must
name the file and propose a concrete split (which functions/classes go where).

Evaluate the code against the acceptance criteria in @STATE_DIR@/tasks/current/adr.md only. plan.md is a soft document: deviations from the plan are not findings when the acceptance criteria hold.
