# spec-kit-llm-client

Installer for a global **planner → executor** workflow on top
of [GitHub Spec Kit](https://github.com/spec-kit/specify-cli) and [OpenCode](https://opencode.ai).

It solves the hand-off problem between a strong model (planning/review) and a cheap model (implementation): sessions
stay **warm** across steps via `opencode run --session`, so the executor does not re-read the whole project at every
step.

Run `install.py` once, edit one config file, and then in any project:

```
specify workflow run ~/.config/spec-kit-llm-client/adr-pipeline.yml -i feature="build a kanban board"
```

Or use the installed global launcher `spec-run` (also from any project, no
`specify init` required):

```
spec-run adr "build a kanban board"
spec-run task "add a dark mode toggle"
spec-run review
spec-run review --branch-diff
```

`spec-run adr "feature"` runs the installed `adr-pipeline` with `-i feature=<feature>`
(all non-flag arguments are joined), `spec-run task "task"` runs the installed
`task-pipeline` with `-i task=<task>` (the task pipeline first studies the
project and researches the approach before writing the ADR), `spec-run review`
runs the `review-pipeline`
(whole codebase by default, `--branch-diff` adds `-i branch-diff=true`), and other
`-i key=value` arguments (e.g. `-i task_id=my-feature`) are passed through unchanged.
`spec-run --help` prints usage. The launcher lives at `~/.local/bin/spec-run` and is
created by `install.py`; add `~/.local/bin` to your `PATH` if it is not there
already (the installer warns about this).

Full cycle: ADR → executor questions → planner answers → implementation → review → fixes until the reviewer says
`VERDICT: PASS`.

A third workflow, `task-pipeline`, starts from a raw task instead of a ready
feature: the planner first studies the project and writes a motivation study
(`study.md`), which you can clarify through a gate (with no round limit: the
full study text is shown in the gate message and the loop continues until you
choose `clear`); then it researches the approach on the web and writes a
proposal (`proposal.md`) with pros/cons/alternatives, and writes the ADR from
the study + proposal — no separate proposal or ADR gate. The executor's
questions are also asked in a loop (up to 3
rounds): after the planner answers, the executor re-asks anything the answers
left open, so questions are closed before implementation instead of surfacing
in the code. Run it with `spec-run task "task description"` or
`specify workflow run ~/.config/spec-kit-llm-client/task-pipeline.yml -i task="..."`.

A second workflow, `review-pipeline`, does the review part alone. By default it
reviews the **entire codebase** of the project and fixes findings:

```
specify workflow run review-pipeline
```

With the optional `branch-diff` input it reviews only the changes between the
current branch and the default branch (`origin/HEAD`, or
`origin/main`/`origin/master`/`main`/`master`, whichever exists) — the diff
includes committed, staged and unstaged changes; it fails with
"nothing to review" when there are none:

```
specify workflow run review-pipeline -i branch-diff=true
```

Both modes write a `review-report.md` into the task directory. It has no
gates — keep the terminal open until it completes.
The same review stages run in both workflows: SRP → bugs → general correctness →
readability "traps", each loop fixing its findings until pass.

specify hides a failing step's stdout/stderr; use the installed wrapper to see
them after a failure:

```
~/.config/opencode/scripts/run-pipeline.py review-pipeline
~/.config/opencode/scripts/run-pipeline.py adr-pipeline -i feature="..."
```

It prefixes every line with an hh:mm:ss timestamp and streams each step's
output as it finishes (from the run state) with the progress marker
`--- step <id> (completed) [N/M]`. While a step runs, a live status block
is shown (ADR-0012/0013): the moment a step starts, a `[harness]` line with
a spinner — 4 frames per second (0.25 s cadence),
`[hh:mm:ss] [harness] <spin> [<step> N/M]` — appears, and the first agent
event of the step replaces it with one line per active process
(`[planner]`/`[planner#<kind>]` for the per-kind review forks) carrying the
cumulative token/cost sums — on the cursor backend too, whose per-turn
`usage` fields are read the same way as the run statistics (no price:
cursor reports no cost). The block is redrawn in place on a TTY; when
stdout is not a TTY no ANSI block is drawn, each step start prints one
plain `[hh:mm:ss] [harness] [<step> N/M]` line and each agent usage event
one plain line — no per-second heartbeat lines ever go into a log. The
engine's own progress lines (`▸ [<step-id>] …`, `Running workflow:`,
`Version:`, `Status:`, `Run ID:`) are not echoed — strictly our format —
while its errors and warnings are re-printed as
`[hh:mm:ss] [harness] <line>` and the interactive gate menu echoes as-is.
On failure it prints the resume command. The per-stage latency table at the
end shows durations in whole minutes plus each stage's share of the total
wall time.

## Requirements

- Linux/macOS
- Python 3 (with `pip3` or `uv` for dependency installation)
- [opencode](https://opencode.ai/docs) 1.18+ on PATH
- [uv](https://docs.astral.sh/uv/) (recommended) or `pipx`/`pip3` — used to install `specify-cli` (>= 0.16)
- `git` in the project you run the workflow in

## Install

```
git clone <this repo>
cd spec-kit-llm-client
python3 install.py
```

The installer:

1. checks prerequisites (python3, opencode, network when needed);
2. installs `specify-cli` (uv → pipx → pip) and PyYAML if missing;
3. creates `~/.config/opencode/agent/{planner,executor}.md`,
   `~/.config/opencode/scripts/` (`run-agent.sh`, `name-task.sh`,
   `save_adr.py`, `check_review.py`, `task_utils.py`),
   `~/.config/spec-kit-llm-client/{config.yml,adr-pipeline.yml,review-pipeline.yml}`
   and the global `~/.local/bin/spec-run` launcher;
4. validates everything (agents visible to opencode, workflow accepted by the
   spec-kit engine, `run-agent.sh` executable).

`python3 install.py` is idempotent — rerun after editing `config.yml` to regenerate
agents and the workflow. `--update` additionally prints newly available config options.

## Configure

Edit `~/.config/spec-kit-llm-client/config.yml`:

```yaml
models:
  planner:
    provider: opencode-go      # opencode provider id
    model: deepseek-v4-pro     # strong model: planning and review
    reasoning: max             # reasoning effort passed to the provider (minimal/low/high/max)
  executor:
    provider: opencode-go
    model: deepseek-v4-flash   # cheap model: implementation
    reasoning: max             # reasoning effort passed to the provider

workflow:
  state_dir: .workflow         # task artifact directory inside a project
  max_fix_iterations: 5        # review-fix loop ceiling
  max_srp_iterations: 5        # SRP review-fix loop ceiling
  max_bug_iterations: 5        # bug review-fix loop ceiling
  max_comment_iterations: 5    # comment (readability) review-fix loop ceiling
  max_adr_iterations: 3        # ADR approve/revise/reject loop ceiling
  max_implement_iterations: 2  # implement verify/retry loop ceiling (guard against an empty implementation)
  max_questions_iterations: 3  # task-pipeline executor questions loop ceiling
  shell_timeout: 7200          # per-step timeout in seconds for agent steps (2h)
  adr_dir: architecture        # directory where approved ADRs are saved
  human_gates: true            # false = gates auto-approve (non-interactive)
  use_serve: false             # true = run-agent.sh passes --attach http://localhost:4096
```

The config file is never overwritten by the installer.

## Usage

In any project (no `specify init` required):

```
specify workflow run ~/.config/spec-kit-llm-client/adr-pipeline.yml -i feature="describe the feature" -i task_id=my-feature
```

`task_id` is required: it names the artifacts (`.workflow/tasks/<task_id>/`) and the
warm sessions (`.workflow/sessions-<task_id>.json`). Use a short, unique id per task —
running a different task with the same `task_id` reuses that task's sessions.

Both commands create the task artifacts in `.workflow/tasks/<task_id>/` (add
`.workflow/` and `.specify/workflows/` to your `.gitignore`).

The task id is optional: when omitted, the first workflow step (`generate-task-id`)
asks the executor to derive a short English kebab-case slug from the feature and
appends a timestamp, so each run gets a human-readable id like
`hello-world-function-20260814-1117` while all steps keep working through the
`.workflow/tasks/current` symlink (sessions are stored per id in
`.workflow/sessions-<task_id>.json`). Pass `-i task_id=<name>` only when you want a
specific id (e.g. to resume a task by name).

When the ADR gate approves, the `save-adr` step releases the ADR into
`architecture/ADR-<XXXX>-<title>.md` (configured via `workflow.adr_dir`): the next
free number after the existing `ADR-*.md` files (0001, 0002, ...) and the `slug`
field from the ADR frontmatter — a short 2-3 word English summary in kebab-case
(e.g. `prod-validation-splits`). If the planner forgot the slug, `save-adr` asks it
to add one (via the warm planner session) and only fails if it still refuses — there
is no transliteration fallback, so filenames never contain non-English titles.
Rerunning the same task id keeps the ADR number — the file is not duplicated
(an auto-generated id produces a fresh task and a fresh ADR on every run). The ADR
heading in the saved file is rewritten to `# ADR-<XXXX>: <title>`.

### Gates, editors and resume

The human touch points are the ADR gate (adr-pipeline) and the feedback
gates: at a feedback gate the wrapper opens your editor with
`.workflow/tasks/current/feedback.md` and the run continues automatically
when the editor closes. A NEW feedback.md is seeded (ADR-0012) with the
numbered questions of the gate's document — the «открытые вопросы» / «Open
Questions» section of `study.md` for the motivation gate, of `adr.md` for
the ADR revise gate — so the questions you are answering are in front of
you while you write; an existing file is never overwritten, and a document
without such a section leaves the file empty. (macOS: TextEdit in a
separate window; Linux: GNOME Text Editor via Flatpak/RPM, or the desktop
opener — the gate then stays interactive and you press `continue` after
closing the window; without a GUI the terminal editor
`$VISUAL → $EDITOR → nano → vi` is used).

At the ADR gate you can choose `approve`, `revise`, or `reject`:

- **approve** — proceed to the executor;
- **revise** — the workflow asks you to write your feedback into
  `.workflow/tasks/current/feedback.md`, then the planner updates the ADR
  accordingly and the gate re-opens with the revised ADR (up to 3 rounds);
- **reject** — abort the run.

If all 3 review rounds run out without an `approve`, a final gate asks you to
approve the ADR as-is or abort — an unapproved ADR is never saved to
`architecture/`.

The final outcome needs no gate: if the planner is satisfied the review loop ends
with `VERDICT: PASS`; if the loop exhausts `max_fix_iterations`, `pass-check` prints
a `WARNING: review loop exhausted ...` line and the run still completes — check the
latest `review-N.md` and the code yourself.

Review and continue (after an abort or a paused gate):

```
specify workflow status
specify workflow resume <run_id>
```

### Implementation deviations and spec sync

The ADR is the source of truth, so a divergence between the plan and the code is
resolved deliberately, not silently:

1. **Record** — when the executor must deviate from the ADR (impossible constraint,
   clearly better approach), it writes `.workflow/tasks/current/deviation.md`
   with: what the ADR says, what it did instead, and why. No file, no deviation.
2. **Review** — the reviewer reads `deviation.md` first. A justified deviation is
   not a finding: the code is judged against the ADR as amended by the deviation.
   A missing or unjustified deviation is reported as a finding and goes through
   the normal fix loop.
3. **Sync** — after the review loop passes, the `sync-adr` step amends `adr.md`
   with an `## Amendments` section (recording what changed and why, without
   rewriting the Decision) and writes the amended ADR over the saved
   `architecture/ADR-XXXX-<title>.md` — same number, same decision, amended. The
   file's git history plus the Amendments section are the durable trace (the
   `.workflow/` artifacts are gitignored).

With `human_gates: false` the ADR gate auto-approves through `verdict_input` defaults;
the workflow runs unattended.

### Warm sessions and review forks

`run-agent.sh` keeps one opencode session per role per task in
`<state_dir>/sessions-<task_id>.json` (default `.workflow/`). The task id is
resolved from the `.workflow/tasks/current` symlink when `--task` is not passed, so
the workflow itself never hardcodes it. Steps continue the same session, so the
agents keep their context between steps. Resuming a run (same id) resumes the same
sessions; a new run (new auto-generated id) starts fresh ones.

The `name-task.sh "<feature>"` script is a one-shot (no session) call that
asks the executor for a short English kebab-case slug — it feeds
`generate-task-id` when the task id is not given explicitly.

Before each step, `run-agent.sh` kills any opencode process it previously recorded
for that session (`<state_dir>/pids/`). This cleans up orphans left behind when a
shell-step timeout kills the workflow shell but not the agent process — a stale
agent can no longer keep writing to the session or burn tokens.

The review-fix-loop checks run in **per-kind forks** of the warm planner session
(ADR-0013): the first check of a kind (`srp`|`bugs`|`review`|`comment`) forks the
warm session once and saves the fork's id in
`<state_dir>/sessions-<task_id>-review-<kind>.json`; every later check of the same
kind continues that same fork (`--review-fork <kind>`), so the reviewer keeps its
past findings across the loop iterations and the scope is read once per run. The
fork's log/pid files are stable per kind
(`sessions-<task_id>-planner-fork-<kind>.jsonl`/`.pid`), so the live status line
is labeled `[planner#<kind>]` and the token sums continue between iterations. The
parent warm session is never mutated. On the cursor backend each kind gets its own
warm chat instead: `create-chat` on the first check, `--resume` on the rest
(cursor has no fork primitive, so the per-kind chat IS the fork). If a per-kind
fork session disappears (opencode auto-compacts or cleans up sessions), the
"Session not found" fallback drops the stale id and forks the parent again.

Long sessions are eventually auto-compacted by opencode. When a session grows too
large, drop it and hand the context over manually. To hand it over explicitly:
summarize the task state into a file, delete the session record, and only then
have the FRESH session read the file back — two calls in the same session would
just re-read what the first wrote (a circular no-op, not a handoff):

```
run-agent.sh executor "summarize the task state into .workflow/tasks/<id>/handoff.md"
rm .workflow/sessions-<task_id>.json   # drop the session between the calls
run-agent.sh executor "read handoff.md and continue"
```

### `opencode serve` mode

Set `workflow.use_serve: true` and start the server yourself:

```
opencode serve
```

`run-agent.sh` will then pass `--attach http://localhost:4096` to `opencode run`.

## How it works

| Artifact       | Written by | Read by           | Rule                                                                 |
|----------------|------------|-------------------|----------------------------------------------------------------------|
| `adr.md`       | planner    | executor, planner | created on step 1                                                    |
| `questions.md` | executor   | planner           | always written; first line `QUESTIONS: NONE` or `QUESTIONS: PRESENT` |
| `answers.md` | planner | executor | written only when `QUESTIONS: PRESENT` |
| `feedback.md` | user | planner | written at the revise gate; cleared after the revision |
| `review-N.md` | planner | executor, planner | first line exactly `VERDICT: PASS` or `VERDICT: FIX` |
| `srp-review-N.md` | planner | executor, planner | first line exactly `SRP: PASS` or `SRP: FIX` |
| `bug-review-N.md` | planner | executor, planner | first line exactly `BUGS: PASS` or `BUGS: FIX` |
| `comment-review-N.md` | planner | executor, planner | first line exactly `VERDICT: PASS` or `VERDICT: FIX` |

The workflow steps: `write-adr` → `adr-loop` (gate with approve/revise/reject →
optional feedback revision) → `save-adr` → `executor-questions` →
`planner-answers` → `implement` → `implement-loop` (`do-while`: verify the
implementation actually changed the repository → if not, the executor is asked
once to redo the work) → `implement-pass-check` (fails the run with an error
when two attempts produced no changes) → `review-fix-loop` (`do-while`: the
four checks — SRP, bugs, general review, readability — run in PARALLEL, each in
its own per-kind fork of the warm planner session (ADR-0013, see "Warm sessions
and review forks"); their findings merge into one document and
the executor fixes everything in one pass; the loop repeats until all four
verdicts pass or `max_fix_iterations` is exhausted) → `sync-adr` → `pass-check`
(reports `REVIEW OK: all verdicts PASS` or a `WARNING` listing the kinds that
never passed).

The `task-pipeline` shares the tail of the adr-pipeline (from `save-adr` to
`pass-check`) but replaces the front: `study` (planner writes `study.md`:
project understanding, reformulated task, presumed motivation, numbered open
questions) → `motivation-loop` (a `study-display` step shows the full
`study.md` in the gate message; the gate is `clear`/`clarify` — on `clarify`
the planner revises `study.md` from your `feedback.md`, and the loop repeats
until `clear`, with no round limit) → `research` (planner uses web search and
writes `proposal.md`: motivation, proposed solution, pros, cons,
alternatives, implementation plan, source links) → `write-adr` (planner
writes `adr.md` from `study.md` + `proposal.md` — no proposal agreement gate,
no separate ADR gate).
The executor's questions are asked in `executor-questions-loop` (up to
`max_questions_iterations`): `executor-questions` rewrites `questions.md` with
the remaining questions (or `QUESTIONS: NONE`), `check_questions.py` checks the
first line, and `planner-answers` answers the current round; after the rounds
run out the pipeline continues with `implement` and the executor works from
`adr.md` + `answers.md`, recording deviations in `deviation.md`.

Before the review stages, `implement-loop` guards against an executor that
finished without doing any work: `check_implementation.py` (installed next to
`check_review.py`) exits non-zero when the repository has no new changes (`git
diff HEAD` empty and no new non-ignored files; the pipeline's own saved
`adr_dir/ADR-*.md` files are excluded). The executor is then asked once with
"You didn't do changes." and, if the second attempt is still empty,
`implement-pass-check` fails the run with an explanation. `run-agent.sh` also
raises opencode's per-response output cap via
`OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=1000000`, so an agent cannot be cut off
mid-reasoning before acting (ADR-0006).

The four review kinds — SRP (single-responsibility violations: god
classes/functions, mixed concerns), bugs (logic errors, wrong conditions, edge
cases, unhandled errors, races, discrepancies with the acceptance criteria),
general review (against `adr.md`/`deviation.md`) and readability "traps"
(correct but misleading code that deserves a *why* comment — never a *what*
description — or a rename/refactor) — now run in parallel (ADR-0009). Before
the loop, `check_review.py pending` lists the kinds whose latest report is not
PASS; a `fan-out` (`max_concurrency: 4`) runs one review per kind, each in its
OWN per-kind fork of the warm planner session (ADR-0013: the first check forks
the parent once and saves the fork id, the later checks continue the same
fork), writing its own numbered report
(`srp-review-N.md`, `bug-review-N.md`, `review-N.md`, `comment-review-N.md`)
with the first-line verdict. The four latest reports are then merged
deterministically into `review-report.md` (one section per kind, no synthesis)
and the executor fixes ALL findings with one `fix-all` prompt. On the next
iteration only the still-failing kinds are re-reviewed (re-review prompts diff
the fixed code against the per-kind `*-snapshot.sha`), until every kind passes
or `workflow.max_fix_iterations` is exhausted — the final `pass-check` then
reports the verdicts (a `WARNING` never fails the run). The cursor backend has
no fork primitive, so there each kind gets its own warm chat instead (minted
with `create-chat` on the first check, resumed with `--resume` on the rest;
the warm-up step is skipped); this is documented in `run-agent-cursor.sh`.

The loop verdict checks the **latest** review file only — the installed
`check_review.py` script (`~/.config/opencode/scripts/check_review.py`) picks
the highest `*-review-N.md` and exits 0 only when its first line is the PASS
marker for that kind. The same script provides `pending` (the fan-out item
list) and `merge` (the deterministic `review-report.md` concatenation, exiting
1 while any kind is not PASS).

## Security notes

- `run-agent.sh` passes `--auto` to `opencode run` (agents may act without
  confirmation; required for headless workflow steps). The agents also carry a
  `permission: {"*": allow}` frontmatter as a fallback for TUI usage.
- The workflow interpolates `{{ inputs.feature }}` into a shell command. Pass only
  trusted, simple feature descriptions; do not pipe untrusted text into `-i feature=`.
- Workflow `shell` steps run with your privileges — review the generated
  `adr-pipeline.yml` before running it.

## Uninstall

```
python3 install.py --uninstall
```

Removes the generated agents, script, workflow and example config (keeps
`config.yml`), then asks whether to uninstall `specify-cli`/PyYAML (`--yes` answers
yes).

## Troubleshooting

- **`error: required input 'feature' not provided`** during install validation is
  expected — it proves the workflow parsed.
- **Session ids**: `run-agent.sh` extracts the `sessionID` field from `opencode run
  --format json` output, with a `sessionId` fallback. If a future opencode version
  changes the stream shape, update `extract_session_id()` in
  `pipeline_scripts/run-agent.sh` (output of `opencode run --format json` prints the
  first `sessionID:...` occurrence).
- **specify-cli version**: the installer pins a minimum version (>= 0.16). The
  workflow schema (`do-while`, `verdict_input`, `continue_on_error`) is verified
  against 0.16.2.
- **Task ids**: keep `task_id` simple (letters, digits, `-`/`_`); it is interpolated
  into shell paths.
- **`opencode agent list` validation** reads the target config dir via
  `XDG_CONFIG_HOME`, so `--home` installs validate correctly.

## Layout

```
install.py                  entry point
config.example.yml          reference config (English comments)
spec_utils/
  cli.py                    argument parsing, flag validation, --update diff
  config.py                 paths, defaults, config.yml loading and validation
  deps.py                   python/uv/pip/specify/pyyaml install AND uninstall
  uninstall.py              --uninstall: remove installed files and dependencies
  render.py                 install the agents, scripts and workflows (no templates)
  verify.py                 validate the installed pipeline
  workflows/
    adr-pipeline.yml        ADR pipeline source (state_dir/adr_dir delivered at runtime)
    review-pipeline.yml     review-only workflow source
    task-pipeline.yml       task -> motivation -> research -> ADR pipeline source
pipeline_scripts/           installed scripts (copied verbatim; config via args/env)
  spec_run.py               global spec-run launcher (~/.local/bin/spec-run)
  run_pipeline.py           run-pipeline.py wrapper (timestamps, logs, statistics)
  run-agent.sh              session glue (planner/executor roles)
  name-task.sh              one-shot task-slug generator (generate-task-id)
  save_adr.py               release/sync an ADR (save, sync)
  check_review.py           verdict gate for the review loops (review/srp/bugs/comment)
  check_questions.py        questions-loop exit condition (QUESTIONS: NONE?)
  check_implementation.py   implement guard (changes present?)
  task_utils.py             shared helpers (task-dir resolution)
  adr_utils.py              text rules for save_adr.py (slug, numbering, headings)
  agent_call.py             reach an agent through run-agent.sh
tests/test_install.py       smoke tests (unittest, all through --home)
```
