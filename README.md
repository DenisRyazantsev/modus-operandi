# Spec Run

## Motivation

Automate repetitive workflows in LLM clients (opencode and cursor).

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
spec-run task "<feature-description>"
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

### Backend

By default, opencode is used. If you need the cursor backend, use the `--backend cursor` flag:

```shell
spec-run --backend cursor task "<feature-description>"
```
