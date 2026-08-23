# Modus Operandi 🤌

Automate spec-driven "planner -> executor" workflows in LLM clients (opencode
and cursor): task planning, task implementing and code review.

## Quick start

```shell
pip install modus-operandi
modus-operandi task "<task-description>"
```

No configuration needed: the defaults use the free OpenCode Zen model
`opencode/big-pickle` for planning, review and implementation, which works
out of the box. To switch models or backends, run `modus-operandi edit`.

## Install

`modus-operandi` works right after install: the first run renders the pipeline
files (agents, scripts, workflows, prompts) into `~/.config/modus-operandi/` and
`~/.config/opencode/`, and creates `~/.config/modus-operandi/config.yml` from the
example. Updates arrive through PyPI (`pip install -U modus-operandi`); the render
is re-applied automatically on the next run.

Requirements: Python >= 3.12, and one backend CLI on PATH — `opencode`
(default) or `cursor-agent` (see `--backend cursor` below).

The dev flow (`python3 install.py` from a checkout) additionally installs a
checkout-based `modus-operandi` command into `~/.local/bin` and keeps that
directory on PATH in your existing shell rc files (`~/.bashrc`, `~/.zshrc`,
`~/.profile`), so the command is available in every newly opened terminal.

## Usage

### Task

If you have a workflow like this

```
1. Studying the motivation of the task with a planner-agent
2. Creating an ADR
3. Writing an implementation plan for the executor
4. The executor-agent asking clarifying questions about the task
5. The planner-agent answering these questions
6. Implementing the task
7. Reviewing for SRP violations
8. Reviewing for bugs
9. General review (correctness and quality)
10. Comment review (readability)
11. Fixing the issues found
```

The ADR records the decision (what and why) and is published to the
`architecture/` directory at the end of the run in its final version; the
implementation plan stays internal to the executor.

then you can use this command

```shell
modus-operandi task "<task-description>"
```

The description can also come from a file: `modus-operandi task path/to/description.md`
(a single argument naming an existing file is read as the description; file
and inline text input are mutually exclusive).

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
rolled back and the error is reported with its line number; a config left
unchanged is not re-applied.

## Uninstall

```shell
modus-operandi uninstall
pip uninstall modus-operandi
```

removes the rendered pipeline files (`~/.config/modus-operandi` and the modus-operandi
files under `~/.config/opencode`) — run `pip uninstall modus-operandi` afterwards
to remove the package itself.
