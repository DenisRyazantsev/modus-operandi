Warm up for this review run: the four checks (SRP, bugs, general review,
readability) will each run in a separate fork of this session. Load the
review scope into your context now, so the forks inherit it and do not
re-discover it.

Read @STATE_DIR@/scope.txt: if it starts with 'branch-diff: ', the in-scope
files are those changed between that base branch and HEAD (plus untracked
files); if it says 'full', every source file in the codebase is in scope.
Run git status (git diff does not show untracked files, so new files appear
only in git status — include them in the scope), and in branch-diff mode run
git diff <base> --name-only to enumerate the changed files. Do not write any
review files.
