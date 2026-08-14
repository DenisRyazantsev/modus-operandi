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

Full cycle: ADR → executor questions → planner answers → implementation → review → fixes until the reviewer says
`VERDICT: PASS`.

A second workflow, `review-pipeline`, does the review part alone: run it after
your own edits and it reviews the uncommitted changes against the default branch
(`origin/HEAD`, or `origin/main`/`origin/master`/`main`/`master`, whichever
exists), fixes findings and writes a `review-report.md`:

```
specify workflow run review-pipeline
```

It has no inputs and no gates — keep the terminal open until it completes.
The same review stages run in both workflows: SRP → bugs → general correctness →
readability "traps", each loop fixing its findings until pass.

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
   `~/.config/opencode/scripts/run-agent.sh` and
   `~/.config/spec-kit-llm-client/{config.yml,adr-pipeline.yml,review-pipeline.yml}`;
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

Optional per-project registration (requires `specify init` in the project first):

```
python3 <repo>/install.py --register
specify workflow run adr-pipeline -i feature="describe the feature"
```

Both commands create the task artifacts in `.workflow/tasks/<task_id>/` (add to your
`.gitignore` — see `templates/gitignore.snippet`).

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

### Gates and resume

The only human touch point is the ADR gate (and the revise feedback gate):

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

### Warm sessions and `--reset`

`run-agent.sh` keeps one opencode session per role per task in
`<state_dir>/sessions-<task_id>.json` (default `.workflow/`). The task id is
resolved from the `.workflow/tasks/current` symlink when `--task` is not passed, so
the workflow itself never hardcodes it. Steps continue the same session, so the
agents keep their context between steps. Resuming a run (same id) resumes the same
sessions; a new run (new auto-generated id) starts fresh ones.

The `run-agent.sh name "<feature>"` subcommand is a one-shot (no session) call that
asks the executor for a short English kebab-case slug — it feeds
`generate-task-id` when the task id is not given explicitly.

Before each step, `run-agent.sh` kills any opencode process it previously recorded
for that session (`<state_dir>/pids/`). This cleans up orphans left behind when a
shell-step timeout kills the workflow shell but not the agent process — a stale
agent can no longer keep writing to the session or burn tokens.

Long sessions are eventually auto-compacted by opencode. When a session grows too
large, drop it and hand the context over manually:

```
run-agent.sh executor "summarize the task state into .workflow/tasks/<id>/handoff.md"
run-agent.sh executor --reset
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
`planner-answers` → `implement` → `srp-loop` (`do-while`: SRP review → verdict →
fix, only for single-responsibility violations) → `srp-pass-check` (reports
`SRP REVIEW OK` or a `WARNING`) → `bug-loop` (`do-while`: bug review → verdict →
fix, only for bugs) → `bug-pass-check` (reports `BUGS REVIEW OK` or a `WARNING`)
→ `review-loop` (`do-while`: review → fix →
verdict) → `sync-adr` → `pass-check` (reports `REVIEW OK` or
`WARNING: review loop exhausted`) → `comment-review-loop` (`do-while`: comment
review → verdict → fix, only for readability "traps" — comments about the *why*,
not bugs) → `comment-pass-check` (reports `COMMENT REVIEW OK` or a `WARNING`).

The review runs in four stages. First `srp-loop` checks the git changes strictly
for single-responsibility violations (god classes/functions, mixed concerns);
the executor fixes the findings and the SRP review repeats until it passes or
`workflow.max_srp_iterations` is exhausted (a `WARNING` is printed and the run
continues). Next `bug-loop` checks the changes strictly for bugs — logic errors,
wrong conditions, edge cases, unhandled errors, races, and discrepancies between
the implemented behavior and the acceptance criteria in `adr.md`; fixes repeat
until `workflow.max_bug_iterations` is exhausted. Then the main `review-loop`
checks the code against the ADR as before. Finally, after `sync-adr` and
`pass-check`, `comment-review-loop` checks
the changes for readability "traps" only — correct but misleading code that
deserves a *why* comment (never a *what* description) or a rename/refactor — and
the executor applies the findings until it passes or
`workflow.max_comment_iterations` is exhausted. Each stage uses its own numbered
review files (`srp-review-N.md`, `bug-review-N.md`, `review-N.md`,
`comment-review-N.md`) so the loops and verdicts never interfere.

The loop verdict checks the **latest** review file only (`sort -V`):
`last=$(ls -1 .../review-*.md 2>/dev/null | sort -V | tail -1) && head -1 "$last" | grep -q '^VERDICT: PASS'`.

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
yes). Projects where you ran `--register` keep their installed copy — remove it with
`specify workflow remove adr-pipeline`.

## Troubleshooting

- **`error: required input 'feature' not provided`** during install validation is
  expected — it proves the workflow parsed.
- **Session ids**: `run-agent.sh` extracts the `sessionID` field from `opencode run
  --format json` output, with a `sessionId` fallback. If a future opencode version
  changes the stream shape, update `extract_session_id()` in
  `templates/run-agent.sh.tpl` (output of `opencode run --format json` prints the
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
templates/
  planner.md.tpl            planner agent (strong model)
  executor.md.tpl           executor agent (cheap model)
  adr-pipeline.yml.tpl      spec-kit workflow
  run-agent.sh.tpl          session glue
  gitignore.snippet         recommended .gitignore lines
tests/test_install.py       smoke tests (unittest, all through --home)
```
