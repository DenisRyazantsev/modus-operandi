# Spec Run

Automate spec-driven "planner -> executor" workflows in LLM clients (opencode
and cursor): task planning, task implementing and code review.

## Quick start

```shell
pip install spec-run
spec-run edit   # pick your models and backend
spec-run task "<task-description>"
```

## Install

`spec-run` works right after install: the first run renders the pipeline
files (agents, scripts, workflows, prompts) into `~/.config/spec-run/` and
`~/.config/opencode/`, and creates `~/.config/spec-run/config.yml` from the
example. Updates arrive through PyPI (`pip install -U spec-run`); the render
is re-applied automatically on the next run.

Requirements: Python >= 3.12, and one backend CLI on PATH — `opencode`
(default) or `cursor-agent` (see `--backend cursor` below).

## Usage

### Task

If you have a workflow like this

```
1. Studying the motivation of the task with a planner-agent
2. Creating an ADR
3. The executor-agent asking clarifying questions about the task
4. The planner-agent answering these questions
5. Implementing the task
6. Reviewing for SRP violations
7. Reviewing for bugs
8. General review (correctness and quality)
9. Comment review (readability)
10. Fixing the issues found
```

then you can use this command

```shell
spec-run task "<task-description>"
```

### Review

If you have a workflow like this

```
1. Reviewing the whole project for SRP violations
2. Reviewing the whole project for bugs
3. Comment review (readability)
4. Fixing the issues found
```

then you can use this command

```shell
spec-run review
```

To review only the changes between the current branch and the default branch:

```shell
spec-run review --branch-diff
```

### Backend

By default, opencode is used. If you need the cursor backend, use the
`--backend cursor` flag:

```shell
spec-run --backend cursor task "<task-description>"
```

### Config

```shell
spec-run edit
```

opens `~/.config/spec-run/config.yml` in your terminal editor. On save and
close it validates the file: a valid config is applied, an invalid one is
rolled back and the error is reported with its line number.

## Uninstall

```shell
spec-run uninstall
pip uninstall spec-run
```

removes the rendered pipeline files (`~/.config/spec-run` and the spec-run
files under `~/.config/opencode`) — run `pip uninstall spec-run` afterwards
to remove the package itself.
