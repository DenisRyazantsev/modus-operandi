# Contributing

## Workflow YAML contains no bash scripts

The workflow files (`src/spec_run/data/workflows/review-pipeline.yml`, `task-pipeline.yml`) are
declarative: they describe the step graph, the gates and the loop conditions. A `type: shell`
step's `run:` value may contain exactly ONE command line that invokes an installed script from
`src/spec_run/data/pipeline_scripts/`, with the workflow inputs and context interpolated as
quoted arguments.

We never write bash scripts in YAML. We only call bash scripts from YAML.

The only shell syntax allowed in a `run:` value is the single path expansion that locates the
scripts directory (so a direct `specify workflow run` without the wrapper's env still finds
them):

```yaml
run: >-
  "${SKLC_SCRIPTS_DIR:-$HOME/.config/opencode/scripts}/some-step.sh"
  "{{ inputs.state_dir }}"
  "{{ inputs.task_id }}"
```

All logic — `if`/`case`/loops, pipes, heredocs, variable assignments, `#` comments — lives in
the bash/python scripts under `src/spec_run/data/pipeline_scripts/`, which the bootstrap and
the dev installer copy to `~/.config/opencode/scripts/` verbatim.

### Why

1. The specify engine folds a `>-` block into a single line. A `#` comment inside a folded
   `run:` block starts a shell comment that swallows the REST of the step, silently turning it
   into a no-op (this actually happened to `warm-planner` in `review-pipeline.yml`; see
   `tests/install/test_workflow_structure.py`).
2. Inline logic cannot be unit-tested and is invisible to `sh -n`; a script in
   `src/spec_run/data/pipeline_scripts/` is tested the same way as `run-agent.sh` and friends.

### Rules

1. Every `type: shell` step calls exactly one script with quoted arguments. No `if`, `for`,
   `&&`, `||`, `|`, no heredocs, no comments, no assignments inside `run:`.
2. New step scripts go into `src/spec_run/data/pipeline_scripts/` and are registered in
   `src/spec_run/paths.py` (install path), `src/spec_run/render.py` (copy rule) and
   `src/spec_run/verify.py` (post-install check).
3. Step scripts resolve their sibling scripts via their own location (`dirname "$0"`), and take
   the workflow inputs as `"$1"`, `"$2"`, ... — the workflows never compute paths or values.
4. New inline logic anywhere in a workflow is a merge-blocker.

## Testing and linting

```
uv run pytest tests -q
uv run ruff check .
uv run mypy
```

The installer tests exercise the full `install.py --home` flow and assert the workflow
structures, so a workflow change without a matching test update fails the suite.
