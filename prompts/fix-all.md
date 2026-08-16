Read @STATE_DIR@/tasks/current/review-report.md and fix all its findings in one
pass. The document concatenates the latest reports of all four review kinds
(SRP, bugs, general review, readability comments); every section and every
FIX finding listed there is in scope. Do not skip a section because another
one is larger — address them all. For comment findings follow the
COMMENT/REFACTOR verdicts (add the suggested why-comment or perform the
rename/refactor). Then run the project's tests/linter if available.
