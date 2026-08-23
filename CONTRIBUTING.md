# Contributing

## Workflow YAML contains no bash scripts

The workflow files (`src/modus_operandi/data/workflows/review-pipeline.yml`, `task-pipeline.yml`) are
declarative: they describe the step graph, the gates and the loop conditions. A `type: shell`
step's `run:` value may contain exactly ONE command line that invokes an installed script from
`src/modus_operandi/data/pipeline_scripts/`, with the workflow inputs and context interpolated as
quoted arguments.

We never write bash scripts in YAML. We only call bash scripts from YAML.

The only shell syntax allowed in a `run:` value is the single path expansion that locates the
scripts directory (so a direct `specify workflow run` without the wrapper's env still finds
them):

```yaml
run: >-
  "${MO_SCRIPTS_DIR:-$HOME/.config/opencode/scripts}/some-step.sh"
  "{{ inputs.state_dir }}"
  "{{ inputs.task_id }}"
```

All logic — `if`/`case`/loops, pipes, heredocs, variable assignments, `#` comments — lives in
the bash/python scripts under `src/modus_operandi/data/pipeline_scripts/`, which the bootstrap and
the dev installer copy to `~/.config/opencode/scripts/` verbatim.

### Why

1. The specify engine folds a `>-` block into a single line. A `#` comment inside a folded
   `run:` block starts a shell comment that swallows the REST of the step, silently turning it
   into a no-op (this actually happened to a workflow step in `review-pipeline.yml`; see
   `tests/install/test_workflow_structure.py`).
2. Inline logic cannot be unit-tested and is invisible to `sh -n`; a script in
   `src/modus_operandi/data/pipeline_scripts/` is tested the same way as `run-agent.sh` and friends.

### Rules

1. Every `type: shell` step calls exactly one script with quoted arguments. No `if`, `for`,
   `&&`, `||`, `|`, no heredocs, no comments, no assignments inside `run:`.
2. New step scripts go into `src/modus_operandi/data/pipeline_scripts/` and are registered in
   `src/modus_operandi/paths.py` (install path), `src/modus_operandi/render.py` (copy rule) and
   `src/modus_operandi/verify.py` (post-install check).
3. Step scripts resolve their sibling scripts via their own location (`dirname "$0"`), and take
   the workflow inputs as `"$1"`, `"$2"`, ... — the workflows never compute paths or values.
4. New inline logic anywhere in a workflow is a merge-blocker.

## CI YAML contains no code

The GitHub Actions files (`.github/workflows/*.yml`) are declarative too: they
select actions, wire the reusable workflows and invoke scripts — they never
embed code. A `run:` value is exactly ONE command line that calls an existing
script, with inputs passed as quoted arguments:

```yaml
run: python3 .github/scripts/set_version.py "$GITHUB_REF_NAME"
```

No bash/python heredocs, no multi-line `run:` blocks, no pipes, no variable
assignments, no `#` comments inside the workflows. All logic lives in the
scripts under `.github/scripts/`, and new inline code in a workflow yml is a
merge-blocker.

### Why

A workflow that embeds a script cannot be linted, type-checked or tested
before it runs in the runner; a script in `.github/scripts/` goes through the
same `ruff`/`mypy` gates as the rest of the repo (the whole tree, see
`pyproject.toml`) and is unit-tested like the pipeline scripts (see
`tests/ci/`).

## Development

From a checkout, `python3 install.py --home <dir>` installs the rendered
pipeline into `<dir>` (used by the tests); run the launcher with
`uv run modus-operandi` (or `python -m modus_operandi.cli`) after `uv sync`.

## Testing and linting

```
uv run pytest tests -q
uv run ruff check .
uv run mypy
```

The installer tests exercise the full `install.py --home` flow and assert the workflow
structures, so a workflow change without a matching test update fails the suite.
