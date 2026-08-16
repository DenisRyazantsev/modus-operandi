Re-review for SRP ONLY: each module (file), class, and function must have
exactly one responsibility — no god classes/functions, no mixed concerns, no
multiple classes per file. The executor fixed the findings from @LATEST@.

The diff is only a marker: it tells you WHICH files the executor changed since
the previous review, not what to review. Verify each finding from @LATEST@ is
fixed, then re-collect the files the executor touched since the previous
review: run git diff @SNAP@ --name-only and git status (git diff does not show
untracked files, so new files made by the executor only appear in git status —
include them). Review each of those files IN FULL, as it exists now — not just
the changed lines.

Skip files with fewer than 300 lines of code — this is a scope filter to keep
the review fast, not an SRP criterion. A skipped small file can still violate
SRP; the filter just accepts that risk for speed.

For each remaining file, the question is: does this file have exactly one
responsibility — one reason to change? Check for god functions, god classes,
mixed abstraction levels, and classless procedural files mixing unrelated
concerns. If a fix added code to a file that is already large and mixing
concerns, this is exactly the moment to split it.

Write @STATE_DIR@/tasks/current/srp-review-@N@.md with the first line exactly
'SRP: PASS' or 'SRP: FIX' followed by actionable findings. Each finding must
name the file and propose a concrete split (which functions/classes go where).
