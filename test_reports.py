#!/usr/bin/env python3
"""test_reports.py - machine-produced coverage/latency reports for the tests review kind.

Part of this repository's test process (ADR-0022): the tests-review review kind
of both pipelines consumes a function-call-level coverage report and a latency
report. Running this script produces both reports plus the machine data they
are derived from (coverage.json, pytest.xml) in one pass.

Usage (run from the repository root):
  uv run python test_reports.py [--out-dir DIR] [--base REF]

Steps: (1) scope = the src/**/*.py files changed since <base> (git diff plus
untracked files; when HEAD is unborn or there is no git repo, every
src/**/*.py file); (2) run the whole test suite once under coverage.py >= 7.6
(its JSON report carries per-function data); (3) emit coverage.json; (4)
classify every function of the scoped files as exercised or not; (5) write
function-coverage.md; (6) write test-latency.md from the junitxml of the same
run. The script writes nothing outside --out-dir and never modifies the
working tree. It needs no network and no LLM.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def default_out_dir() -> Path:
    """The state dir's tasks/current (MO_STATE_DIR), .workflow/tasks/current otherwise."""
    state = os.environ.get("MO_STATE_DIR")
    if state:
        return Path(state) / "tasks" / "current"
    return Path(".workflow") / "tasks" / "current"


def _run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)


@dataclass(frozen=True)
class Scope:
    """The review scope: changed src Python files plus everything informational."""

    base_ref: str
    scope_files: tuple[str, ...]
    informational: tuple[str, ...]


def collect_scope(base: str) -> Scope:
    """The changed src/**/*.py files since base, or all of them without git.

    Deleted paths cannot be covered by the suite: they are dropped from both
    lists (git diff --name-only lists them too). Untracked files are read via
    `git ls-files --others --exclude-standard` because git diff does not show
    them. Without a resolvable HEAD (unborn HEAD, or not a git repo) the scope
    falls back to every src/**/*.py file.
    """
    head = _run(["git", "rev-parse", "--verify", "--quiet", "HEAD"])
    if head.returncode != 0:
        files = tuple(sorted(str(p) for p in Path("src").rglob("*.py")))
        return Scope(base_ref=base, scope_files=files, informational=())
    diff = _run(["git", "diff", "--name-only", base])
    if diff.returncode != 0:
        detail = (diff.stderr or diff.stdout).strip()
        raise SystemExit(f"error: git diff {base} failed:\n{detail}")
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"])
    changed = sorted({*diff.stdout.splitlines(), *untracked.stdout.splitlines()})
    existing = [p for p in changed if Path(p).is_file()]
    scope = tuple(p for p in existing if p.startswith("src/") and p.endswith(".py"))
    informational = tuple(p for p in existing if p not in scope)
    return Scope(base_ref=base, scope_files=scope, informational=informational)


@dataclass(frozen=True)
class FunctionStat:
    """One function of a changed module, as reported by coverage.py."""

    name: str
    exercised: bool


@dataclass(frozen=True)
class FileFunctions:
    """The function stats of one changed module present in the coverage report."""

    path: str
    functions: tuple[FunctionStat, ...]


def parse_function_coverage(
    data: dict[str, Any], scope: Sequence[str]
) -> tuple[tuple[FileFunctions, ...], tuple[str, ...]]:
    """Classify the scoped files' functions from a coverage.py JSON report.

    Classification rule (from the probe of the actual coverage.py >= 7.6 JSON
    shape, ADR-0022): a function is exercised iff at least one of its body
    statements executed. The probe showed that coverage.py never counts the
    def/signature line as executed for the function's own entry (an
    imported-only function has an empty executed_lines), so exercised iff
    executed_lines is non-empty. The empty-named module-level pseudo-entry is
    not a function and is skipped. Files absent from the report were never
    imported by the suite: every function of theirs is unexercised, and the
    caller reports them separately.
    """
    files: dict[str, Any] = data.get("files", {})
    present: list[FileFunctions] = []
    absent: list[str] = []
    for path in scope:
        entry = files.get(path)
        if entry is None:
            absent.append(path)
            continue
        functions: dict[str, Any] = entry.get("functions", {}) if isinstance(entry, dict) else {}
        stats: list[FunctionStat] = []
        for name, info in functions.items():
            if not name:
                continue  # the module-level pseudo-entry ("") is not a function
            executed = bool(info.get("executed_lines")) if isinstance(info, dict) else False
            stats.append(FunctionStat(name=name, exercised=executed))
        present.append(FileFunctions(path=path, functions=tuple(stats)))
    return tuple(present), tuple(absent)


@dataclass(frozen=True)
class TestCaseStat:
    """One testcase of the junitxml report (informational latency data)."""

    file: str
    name: str
    seconds: float


@dataclass(frozen=True)
class JunitSummary:
    """The junitxml facts the latency report is built from."""

    wall_seconds: float
    test_count: int
    cases: tuple[TestCaseStat, ...]


def parse_junit(xml_text: str) -> JunitSummary:
    """Parse a pytest junitxml report (xunit2: one <testsuite> root element).

    The testsuite time attribute is the suite wall time; per <testcase> the
    time, classname/file and name attributes are read. The file attribute
    names the test module; classname is the fallback for the per-file sums.
    """
    root = ET.fromstring(xml_text)
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise ValueError("no <testsuite> element in the junitxml report")
    wall = float(suite.attrib.get("time", "0") or 0)
    count = int(suite.attrib.get("tests", "0"))
    cases: list[TestCaseStat] = []
    for case in suite.iter("testcase"):
        file = case.attrib.get("file") or case.attrib.get("classname", "")
        name = case.attrib.get("name", "")
        seconds = float(case.attrib.get("time", "0") or 0)
        cases.append(TestCaseStat(file=file, name=name, seconds=seconds))
    return JunitSummary(wall_seconds=wall, test_count=count, cases=tuple(cases))


def render_function_report(
    scope: Scope,
    date: str,
    suite_line: str,
    per_file: Sequence[FileFunctions],
    absent: Sequence[str],
) -> str:
    """function-coverage.md: machine-readable facts only, no advice."""
    total = sum(len(f.functions) for f in per_file)
    exercised = sum(1 for f in per_file for s in f.functions if s.exercised)
    percent = round(100 * exercised / total) if total else 0
    lines = [
        "# Function coverage report",
        "",
        f"- date: {date}",
        f"- base: {scope.base_ref}",
        f"- suite: {suite_line}",
        "",
        f"- scope: {len(scope.scope_files)} changed src Python files, {total} functions, "
        f"{exercised} exercised ({percent}%)",
        "",
    ]
    for file in per_file:
        lines.append(f"## {file.path}")
        file_total = len(file.functions)
        file_exercised = sum(1 for s in file.functions if s.exercised)
        lines.append(f"exercised: {file_exercised}/{file_total}")
        for stat in file.functions:
            if not stat.exercised:
                lines.append(f"- {stat.name}")
        lines.append("")
    if absent:
        lines.append("## modules never imported by the test suite")
        lines.append("")
        lines.extend(f"- {path}" for path in absent)
        lines.append("")
    if scope.informational:
        lines.append("## changed files outside function-coverage scope (informational)")
        lines.append("")
        lines.extend(f"- {path}" for path in scope.informational)
        lines.append("")
    return "\n".join(lines)


def render_latency_report(summary: JunitSummary, date: str) -> str:
    """test-latency.md: suite wall time, the 20 slowest tests, per-file sums."""
    lines = [
        "# Test latency report",
        "",
        f"- date: {date}",
        f"- suite wall time: {summary.wall_seconds:.2f}s ({summary.test_count} tests)",
        "",
        "## 20 slowest tests",
        "",
    ]
    slowest = sorted(summary.cases, key=lambda c: c.seconds, reverse=True)[:20]
    for i, case in enumerate(slowest, start=1):
        lines.append(f"{i}. `{case.file}::{case.name}` - {case.seconds:.2f}s")
    lines.extend(["", "## per-file sums", ""])
    totals: dict[str, float] = {}
    for case in summary.cases:
        totals[case.file] = totals.get(case.file, 0.0) + case.seconds
    for file, total in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"- {file}: {total:.2f}s")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=default_out_dir(),
        help="where the reports land (default: $MO_STATE_DIR/tasks/current, "
        "or .workflow/tasks/current when MO_STATE_DIR is unset)",
    )
    parser.add_argument(
        "--base",
        default="HEAD",
        help="git ref the changed-file scope is diffed against (default: HEAD)",
    )
    args = parser.parse_args(argv)
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    scope = collect_scope(args.base)
    env = os.environ.copy()
    env["COVERAGE_FILE"] = str(out / ".coverage")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    junit = out / "pytest.xml"
    suite = _run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--source=src",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--junitxml",
            str(junit),
            "tests",
        ],
        env=env,
    )
    if suite.returncode != 0:
        # Reports are only meaningful for a green suite: keep the out dir
        # free of stale artifacts of the failed run - the failed run's own
        # outputs AND any derived reports an earlier successful run into the
        # same out dir left behind (a reader could mistake an old,
        # date-stamped report for current evidence).
        junit.unlink(missing_ok=True)
        (out / ".coverage").unlink(missing_ok=True)
        (out / "coverage.json").unlink(missing_ok=True)
        (out / "function-coverage.md").unlink(missing_ok=True)
        (out / "test-latency.md").unlink(missing_ok=True)
        print(f"test suite failed (exit {suite.returncode}): reports not produced", file=sys.stderr)
        return 2
    emitted = _run(
        [
            sys.executable,
            "-m",
            "coverage",
            "json",
            "--pretty-print",
            "-o",
            str(out / "coverage.json"),
        ],
        env=env,
    )
    if emitted.returncode != 0:
        print(
            "coverage json failed: " + (emitted.stderr or emitted.stdout).strip(), file=sys.stderr
        )
        return 2
    (out / ".coverage").unlink(missing_ok=True)

    coverage_data: dict[str, Any] = json.loads(
        (out / "coverage.json").read_text(encoding="utf-8")
    )
    per_file, absent = parse_function_coverage(coverage_data, scope.scope_files)
    summary = parse_junit((out / "pytest.xml").read_text(encoding="utf-8"))
    today = datetime.date.today().isoformat()
    (out / "function-coverage.md").write_text(
        render_function_report(
            scope, today, f"passed, {summary.test_count} tests", per_file, absent
        ),
        encoding="utf-8",
    )
    (out / "test-latency.md").write_text(render_latency_report(summary, today), encoding="utf-8")

    print(f"out dir: {out}")
    print(f"wrote: {out / 'function-coverage.md'}")
    print(f"wrote: {out / 'test-latency.md'}")
    print(f"wrote: {out / 'coverage.json'}")
    print(f"wrote: {out / 'pytest.xml'}")
    total = sum(len(f.functions) for f in per_file)
    exercised = sum(1 for f in per_file for s in f.functions if s.exercised)
    print(
        f"function report: {len(per_file)} changed modules measured, "
        f"{exercised} of {total} functions exercised, {len(absent)} modules never imported"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
