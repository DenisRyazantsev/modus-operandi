Write a high-level summary of what was ultimately done in this run into @STATE_DIR@/tasks/current/summary.md.

You are the executor who did the work; your session already knows what happened — the implementation and any fixes from the review loop. If your session lost that context (for example it was restarted), ground yourself in the task artifacts instead: the latest review-*.md / review-report.md files and the current git state (git status / git diff); plan.md and adr.md are task-pipeline-only artifacts, available there as additional grounding.

The summary is shown to the human right after the run and may be used as a commit message or release notes. Requirements:

- High-level: the essence of what changed, grouped by logical area — do NOT enumerate every changed file (the diff itself shows the files).
- Cover, when applicable: what was done and why; deviations from plan.md and why; how the work was verified (tests/linter commands run and their outcome); the outcome of the review findings (which kinds found issues and how they were resolved).
- Write it in English, as markdown, in a few short sections (for example "What was done", "Deviations from the plan", "Verification", "Review outcome"); omit a section entirely when it has no content.
- Be factual: do not invent details; if something was not done or not verified, say so explicitly.
