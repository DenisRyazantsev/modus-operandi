Find SRP violations in the code. Do not review bugs or style (a later stage
does). A module (file), class, and function must each have exactly one
responsibility — one reason to change.

The diff is only a marker: it tells you WHICH files are in scope, not what to
review. Read @STATE_DIR@/scope.txt: if it starts with 'branch-diff: ', the
in-scope files are those changed between that base branch and HEAD (plus
untracked files, see below); if it says 'full', every source file in the
codebase is in scope. Run git status (git diff does not show untracked files,
so new files appear only in git status — include them in the review scope),
and in branch-diff mode run git diff <base> --name-only to enumerate the
changed files. Review each in-scope file IN FULL, as it exists now — not just
the added or changed lines.

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
of size. However: if code was just added to a file that is already large and
mixing concerns, this is exactly the moment to split it, and do not grow a new
concern inside an existing monolith.

Write @STATE_DIR@/tasks/current/srp-review-@N@.md with the first line exactly
'SRP: PASS' or 'SRP: FIX' followed by actionable findings. Each finding must
name the file and propose a concrete split (which functions/classes go where).
