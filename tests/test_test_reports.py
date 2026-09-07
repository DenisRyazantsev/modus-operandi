"""Tests for the root-level test_reports.py (the tests review kind's reports).

The unit samples mirror the shapes observed in the probe of the real
coverage.py >= 7.6 JSON report and of the pytest junitxml report (ADR-0022).
The end-to-end test runs real subprocesses (repo mock policy: no mocks here).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import test_reports

REPO_ROOT = Path(__file__).resolve().parent.parent


def sample_coverage() -> dict[str, Any]:
    """A coverage.json-shaped dict: two src modules, one module not imported."""
    return {
        "files": {
            "src/calc.py": {
                "functions": {
                    "add": {
                        "executed_lines": [2],
                        "missing_lines": [],
                        "excluded_lines": [],
                        "summary": {"percent_covered": 100.0},
                        "start_line": 1,
                    },
                    "never_called": {
                        "executed_lines": [],
                        "missing_lines": [5],
                        "excluded_lines": [],
                        "summary": {"percent_covered": 0.0},
                        "start_line": 4,
                    },
                    "": {  # the module-level pseudo-entry: not a function
                        "executed_lines": [1, 4],
                        "summary": {"percent_covered": 100.0},
                        "start_line": 1,
                    },
                },
                "summary": {"percent_covered": 75.0},
            },
            "src/other.py": {
                "functions": {
                    "worked": {
                        "executed_lines": [2],
                        "missing_lines": [],
                        "summary": {"percent_covered": 100.0},
                        "start_line": 1,
                    },
                    "also_worked": {
                        "executed_lines": [4],
                        "missing_lines": [],
                        "summary": {"percent_covered": 100.0},
                        "start_line": 3,
                    },
                },
                "summary": {"percent_covered": 100.0},
            },
        },
        "meta": {},
    }


SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="3" errors="0" failures="0" time="1.25">
  <testcase classname="tests.test_a" name="test_one" time="0.9" file="tests/test_a.py" line="1"/>
  <testcase classname="tests.test_a" name="test_two" time="0.05" file="tests/test_a.py" line="5"/>
  <testcase classname="tests.test_b" name="test_three" time="0.3" file="tests/test_b.py" line="2"/>
</testsuite>
"""


class FunctionCoverageParseTest(unittest.TestCase):
    def parse(
        self, scope: tuple[str, ...]
    ) -> tuple[tuple[test_reports.FileFunctions, ...], tuple[str, ...]]:
        return test_reports.parse_function_coverage(sample_coverage(), scope)

    def test_exercised_iff_a_body_statement_executed(self) -> None:
        # The probe established that coverage.py never counts the def line as
        # executed for the function's own entry (ADR-0022), so an empty
        # executed_lines means the function was never called.
        per_file, absent = self.parse(("src/calc.py",))
        (calc,) = per_file
        self.assertEqual(
            calc.functions,
            (
                test_reports.FunctionStat(name="add", exercised=True),
                test_reports.FunctionStat(name="never_called", exercised=False),
            ),
        )
        self.assertEqual(absent, ())
        self.assertNotIn(
            "", [s.name for s in calc.functions], "the module-level pseudo-entry must be skipped"
        )

    def test_module_absent_from_report_is_not_imported(self) -> None:
        per_file, absent = self.parse(("src/calc.py", "src/never_imported.py"))
        self.assertEqual([f.path for f in per_file], ["src/calc.py"])
        self.assertEqual(absent, ("src/never_imported.py",))

    def test_all_exercised_module(self) -> None:
        per_file, absent = self.parse(("src/other.py",))
        self.assertEqual(len(per_file), 1)
        self.assertTrue(all(s.exercised for s in per_file[0].functions))
        self.assertEqual(absent, ())


class FunctionReportRenderTest(unittest.TestCase):
    def test_function_report_sections_and_totals(self) -> None:
        scope = test_reports.Scope(
            base_ref="HEAD",
            scope_files=("src/calc.py", "src/other.py", "src/never_imported.py"),
            informational=("README.md", "src/modus_operandi/data/roles/reviewer-tests.md"),
        )
        per_file, absent = test_reports.parse_function_coverage(
            sample_coverage(), scope.scope_files
        )
        md = test_reports.render_function_report(
            scope, "2026-09-07", "passed, 42 tests", per_file, absent
        )
        self.assertIn("# Function coverage report", md)
        self.assertIn("- date: 2026-09-07", md)
        self.assertIn("- base: HEAD", md)
        self.assertIn("- suite: passed, 42 tests", md)
        # 3 of the 4 functions across the two imported modules are exercised.
        self.assertIn(
            "- scope: 3 changed src Python files, 4 functions, 3 exercised (75%)", md
        )
        self.assertIn("## src/calc.py", md)
        self.assertIn("exercised: 1/2", md)
        self.assertIn("- never_called", md)
        self.assertIn("## modules never imported by the test suite", md)
        self.assertIn("- src/never_imported.py", md)
        self.assertIn("## changed files outside function-coverage scope (informational)", md)
        self.assertIn("- README.md", md)


class JunitParseTest(unittest.TestCase):
    def test_wall_time_and_test_count(self) -> None:
        summary = test_reports.parse_junit(SAMPLE_XML)
        self.assertEqual(summary.wall_seconds, 1.25)
        self.assertEqual(summary.test_count, 3)
        self.assertEqual(
            summary.cases,
            (
                test_reports.TestCaseStat(file="tests/test_a.py", name="test_one", seconds=0.9),
                test_reports.TestCaseStat(file="tests/test_a.py", name="test_two", seconds=0.05),
                test_reports.TestCaseStat(file="tests/test_b.py", name="test_three", seconds=0.3),
            ),
        )

    def test_slowest_first_and_per_file_sums(self) -> None:
        summary = test_reports.parse_junit(SAMPLE_XML)
        md = test_reports.render_latency_report(summary, "2026-09-07")
        lines = md.splitlines()
        self.assertIn("1. `tests/test_a.py::test_one` - 0.90s", lines)
        self.assertIn("2. `tests/test_b.py::test_three` - 0.30s", lines)
        self.assertIn("3. `tests/test_a.py::test_two` - 0.05s", lines)
        self.assertIn("- tests/test_a.py: 0.95s", lines)
        self.assertIn("- tests/test_b.py: 0.30s", lines)
        self.assertIn("## 20 slowest tests", md)
        self.assertIn("- suite wall time: 1.25s (3 tests)", md)


class DefaultOutDirTest(unittest.TestCase):
    def test_prefers_mo_state_dir(self) -> None:
        previous = os.environ.get("MO_STATE_DIR")
        os.environ["MO_STATE_DIR"] = "/tmp/state-root"
        try:
            self.assertEqual(
                test_reports.default_out_dir(), Path("/tmp/state-root") / "tasks" / "current"
            )
        finally:
            if previous is None:
                os.environ.pop("MO_STATE_DIR", None)
            else:
                os.environ["MO_STATE_DIR"] = previous

    def test_falls_back_to_dot_workflow(self) -> None:
        previous = os.environ.get("MO_STATE_DIR")
        os.environ.pop("MO_STATE_DIR", None)
        try:
            self.assertEqual(
                test_reports.default_out_dir(), Path(".workflow") / "tasks" / "current"
            )
        finally:
            if previous is not None:
                os.environ["MO_STATE_DIR"] = previous


class EndToEndReportGenerationTest(unittest.TestCase):
    """Real subprocesses (repo mock policy): a temp project without git.

    The temp dir has src/calc.py (one function used by a test, one never
    called) and tests/test_calc.py; the script runs with cwd = temp dir,
    which exercises the non-git fallback (scope = all src/**/*.py).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "calc.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n\n\n"
            "def never_called() -> int:\n    return 42\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_calc.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))\n"
            "\n"
            "from calc import add\n"
            "\n"
            "\n"
            "def test_add() -> None:\n"
            "    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        self.out = self.root / "reports"

    def test_end_to_end_generates_both_reports(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "test_reports.py"), "--out-dir", str(self.out)],
            cwd=str(self.root),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        coverage = (self.out / "function-coverage.md").read_text(encoding="utf-8")
        self.assertIn("## src/calc.py", coverage)
        self.assertIn("exercised: 1/2", coverage)
        self.assertIn("- never_called", coverage)
        self.assertIn(
            "- scope: 1 changed src Python files, 2 functions, 1 exercised (50%)", coverage
        )
        self.assertNotIn("modules never imported", coverage)
        latency = (self.out / "test-latency.md").read_text(encoding="utf-8")
        self.assertIn("suite wall time:", latency)
        self.assertIn("(1 tests)", latency)
        self.assertTrue((self.out / "pytest.xml").is_file())
        self.assertTrue((self.out / "coverage.json").is_file())


class CommittedBranchDiffScopeTest(unittest.TestCase):
    """Regression: a committed branch diff must be coverable via --base.

    The default --base HEAD diffs only the working tree, so in a review-pipeline
    branch-diff run over committed changes (clean tree) the plain invocation
    yields an empty function report. The review-namespace prompts and
    CONTRIBUTING.md now instruct generating with the scope base; this test
    pins the scoping behavior the instruction relies on. Real git + real
    subprocesses (repo mock policy: no mocks here).
    """

    def setUp(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git not available")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name) / "proj"
        self.proj.mkdir()
        (self.proj / "src").mkdir()
        (self.proj / "tests").mkdir()
        # The out dirs live OUTSIDE the repo so a run's own outputs never
        # become untracked files of the next run's scope scan.
        self.out_default = Path(self.tmp.name) / "out-default"
        self.out_base = Path(self.tmp.name) / "out-base"
        self._git("init", "-b", "main")
        self._git("config", "user.name", "Test")
        self._git("config", "user.email", "test@example.com")
        (self.proj / "src" / "calc.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
        )
        (self.proj / "tests" / "test_calc.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))\n"
            "\n"
            "from calc import add\n"
            "\n"
            "\n"
            "def test_add() -> None:\n"
            "    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        self._git("add", "-A")
        self._git("commit", "-m", "base")
        # The committed change under review (the branch-diff vs HEAD~1).
        (self.proj / "src" / "calc.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n\n\n"
            "def never_called() -> int:\n    return 42\n",
            encoding="utf-8",
        )
        self._git("add", "-A")
        self._git("commit", "-m", "add never_called")

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(self.proj), check=True, capture_output=True, text=True
        )

    def run_reports(self, out: Path, *extra: str) -> str:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "test_reports.py"), "--out-dir", str(out), *extra],
            cwd=str(self.proj),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return (out / "function-coverage.md").read_text(encoding="utf-8")

    def test_default_scope_is_empty_for_a_committed_diff(self) -> None:
        # The tree is clean and the change is committed: plain HEAD diff
        # covers nothing — the empty-report trap the branch-diff instruction
        # exists to avoid.
        coverage = self.run_reports(self.out_default)
        self.assertIn(
            "- scope: 0 changed src Python files, 0 functions, 0 exercised (0%)", coverage
        )
        self.assertNotIn("## src/calc.py", coverage)

    def test_scope_base_covers_the_committed_diff(self) -> None:
        # The documented branch-diff invocation (CONTRIBUTING.md): generate
        # with the scope base so the report lists the committed files.
        coverage = self.run_reports(self.out_base, "--base", "HEAD~1")
        self.assertIn(
            "- scope: 1 changed src Python files, 2 functions, 1 exercised (50%)", coverage
        )
        self.assertIn("## src/calc.py", coverage)
        self.assertIn("- never_called", coverage)


if __name__ == "__main__":
    unittest.main()
