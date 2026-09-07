Read @STATE_DIR@/tasks/current/review-report.md and fix all its findings in one
pass. The document concatenates the latest reports of all five review kinds
(SRP, bugs, general review, readability comments, tests review); every section and every
FIX finding listed there is in scope. Do not skip a section because another
one is larger — address them all. For comment findings follow the
COMMENT/REFACTOR verdicts (add the suggested why-comment or perform the
rename/refactor). Then run the project's tests/linter if available. After the
tests pass, regenerate the coverage/latency reports used by the tests review
(run the project's documented report command) so the reviewers see the fixed
state. In a review run whose @STATE_DIR@/scope.txt starts with 'branch-diff:
<base>', run that command against the base it names (the reviewed diff may be
committed, so a working-tree diff would produce empty reports; the project's
documentation states the report command's base argument).
