# Modus Operandi 🤌

Automate spec-driven "planner -> executor" workflows in LLM clients (opencode
and cursor): task planning, task implementing and code review.

## Quick start

```shell
pip install modus-operandi
modus-operandi edit   # pick your models and backend
modus-operandi task "<task-description>"
```

## Install

`modus-operandi` works right after install: the first run renders the pipeline
files (agents, scripts, workflows, prompts) into `~/.config/modus-operandi/` and
`~/.config/opencode/`, and creates `~/.config/modus-operandi/config.yml` from the
example. Updates arrive through PyPI (`pip install -U modus-operandi`); the render
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
modus-operandi task "<task-description>"
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
modus-operandi review
```

To review only the changes between the current branch and the default branch:

```shell
modus-operandi review --branch-diff
```

### Backend

By default, opencode is used. If you need the cursor backend, use the
`--backend cursor` flag:

```shell
modus-operandi --backend cursor task "<task-description>"
```

### Config

```shell
modus-operandi edit
```

opens `~/.config/modus-operandi/config.yml` in your terminal editor. On save and
close it validates the file: a valid config is applied, an invalid one is
rolled back and the error is reported with its line number.

## Uninstall

```shell
modus-operandi uninstall
pip uninstall modus-operandi
```

removes the rendered pipeline files (`~/.config/modus-operandi` and the modus-operandi
files under `~/.config/opencode`) — run `pip uninstall modus-operandi` afterwards
to remove the package itself.
