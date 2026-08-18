#!/usr/bin/env python3
"""validate_inputs.py - validate the pipeline inputs against shell injection.

Usage:
  validate_inputs.py task-id <run_id>
  validate_inputs.py feature <run_id>
  validate_inputs.py task <run_id>

The values are later embedded inside double-quoted shell arguments
(generate-task-id, write-adr, save-adr), so they must be rejected when they
contain characters that could break out of those quotes. The values are read
as JSON data from the run's persisted inputs (.specify/workflows/runs/...) and
validated in python, where the text never enters a shell context:

- interpolating the raw value into a shell validation script is itself the
  injection vector (a task id like `"; touch x; echo "` would run the touch
  while the step text renders);
- a heredoc read is unsafe for the feature (a feature line equal to the
  delimiter would terminate the heredoc at parse time and the remaining
  feature lines would execute as shell).

task-id rejects anything outside [A-Za-z0-9_-]; feature and task reject
double quote, backtick, dollar sign and backslash.

The run id comes from the workflow context ({{ context.run_id }}), not from
"newest directory by mtime": a concurrently started run, or a resumed run
whose directory keeps its original mtime, would make the newest-directory
lookup pick a different run and silently skip or wrongly reject this
feature's validation.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


def _load_inputs(run_id: str) -> dict[str, Any]:
    if not run_id:
        print(
            "error: cannot locate the current run state; cannot validate the input",
            file=sys.stderr,
        )
        sys.exit(1)
    path = ".specify/workflows/runs/" + run_id + "/inputs.json"
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        print("error: cannot read run inputs: " + str(exc), file=sys.stderr)
        sys.exit(1)
    inputs = data.get("inputs")
    return inputs if isinstance(inputs, dict) else {}


def cmd_task_id(run_id: str) -> None:
    task_id = _load_inputs(run_id).get("task_id") or ""
    if task_id and not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        print(
            "error: task_id contains unsupported characters; use only letters, digits, "
            "underscore or dash",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_feature(run_id: str) -> None:
    feature = _load_inputs(run_id).get("feature") or ""
    if re.search(r"[\"`$\\]", feature):
        print(
            "error: feature contains characters unsafe for shell (quote, backtick, "
            "dollar, backslash); rephrase it",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_task(run_id: str) -> None:
    task = _load_inputs(run_id).get("task") or ""
    if re.search(r"[\"`$\\]", task):
        print(
            "error: task contains characters unsafe for shell (quote, backtick, "
            "dollar, backslash); rephrase it",
            file=sys.stderr,
        )
        sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2 or args[0] not in ("task-id", "feature", "task"):
        print(__doc__, file=sys.stderr)
        return 2
    if args[0] == "task-id":
        cmd_task_id(args[1])
    elif args[0] == "feature":
        cmd_feature(args[1])
    else:
        cmd_task(args[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
