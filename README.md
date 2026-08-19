# Spec Run

## Motivation

Automize repetitive workflows in LLM clients (opencode and cursor).

## Usage

### Task

If you have a workflow like this

```
1. Discussion about a task with a planner-agent
2. ADR creating
3. Asking questions about a task from an executor-agent
4. Answering on these questions
5. Implementing task
6. Review for the SRP violations
7. Review for bugs
8. Review for alignment with a plan
9. Review to add comments
10. Fix issues
```

then you can use this command

```shell
spec-run task "<feature-description>"
```

### Review

If you have a workflow like this

```
1. Review a whole project for the SRP violations
2. Review a whole project for bugs
3. Review to add comments
4. Fix issues
```

then you can use this command

```shell
spec-run review
```

### Backend

By default, the opencode is used. In a case if you need the cursor you can use `--backend cursor` flag:

```shell
spec-run --backend cursor task "<feature-description>"
```
