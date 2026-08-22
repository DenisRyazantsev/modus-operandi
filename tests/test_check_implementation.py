"""Unit tests for pipeline_scripts/check_implementation.py (implement guard)."""

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent

_PS_DIR = REPO_ROOT / "src" / "modus_operandi" / "data" / "pipeline_scripts"

_SPEC = importlib.util.spec_from_file_location(
    "check_implementation", _PS_DIR / "check_implementation.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_implementation = importlib.util.module_from_spec(_SPEC)
sys.modules["check_implementation"] = check_implementation
_SPEC.loader.exec_module(check_implementation)


class FakeResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_with_side_effect(side_effect: Any) -> mock._patch[Any]:
    return mock.patch.object(check_implementation, "run_git", side_effect=side_effect)


class HasChangesTest(unittest.TestCase):
    def test_no_changes(self) -> None:
        with run_with_side_effect([FakeResult(0), FakeResult(0, "")]):
            result = check_implementation.has_changes("architecture")
            self.assertEqual(result, (False, "no changes"))

    def test_tracked_changes(self) -> None:
        # git diff --quiet exits 1 when tracked files differ.
        with run_with_side_effect([FakeResult(1), FakeResult(0, "")]):
            self.assertTrue(check_implementation.has_changes("architecture")[0])

    def test_untracked_new_file(self) -> None:
        with run_with_side_effect([FakeResult(0), FakeResult(0, "templates/new.py\n")]):
            changes, summary = check_implementation.has_changes("architecture")
            self.assertTrue(changes)
            self.assertIn("new file(s)", summary)

    def test_only_saved_adr_is_not_a_change(self) -> None:
        # The pipeline's own saved ADR (architecture/ADR-*.md) is untracked
        # but is not executor work; without the exclusion an empty implement
        # would always "pass".
        with run_with_side_effect(
            [FakeResult(0), FakeResult(0, "architecture/ADR-0007-executor-guard.md\n")]
        ):
            result = check_implementation.has_changes("architecture")
            self.assertEqual(result, (False, "no changes"))

    def test_saved_adr_plus_code_file_counts(self) -> None:
        with run_with_side_effect(
            [FakeResult(0), FakeResult(0, "architecture/ADR-0007-x.md\ntemplates/new.py\n")]
        ):
            self.assertTrue(check_implementation.has_changes("architecture")[0])

    def test_diff_error_is_reported(self) -> None:
        with run_with_side_effect([FakeResult(128, stderr="fatal: not a git repo")]):
            changes, summary = check_implementation.has_changes("architecture")
            self.assertFalse(changes)
            self.assertIn("git diff failed", summary)

    def test_ls_files_error_is_reported(self) -> None:
        with run_with_side_effect([FakeResult(0), FakeResult(128, stderr="fatal: git error")]):
            changes, summary = check_implementation.has_changes("architecture")
            self.assertFalse(changes)
            self.assertIn("git ls-files failed", summary)

    def test_custom_adr_dir_exclusion(self) -> None:
        with run_with_side_effect([FakeResult(0), FakeResult(0, "docs/ADR-0001-x.md\n")]):
            self.assertEqual(check_implementation.has_changes("docs"), (False, "no changes"))


class ExitCodeTest(unittest.TestCase):
    def test_changes_exit_zero_no_changes_exit_one(self) -> None:
        codes = []
        with (
            mock.patch.object(
                check_implementation.sys,
                "exit",
                side_effect=lambda code: codes.append(code),
            ),
            mock.patch.object(
                check_implementation,
                "has_changes",
                side_effect=[(True, "tracked files modified"), (False, "no changes")],
            ),
        ):
            check_implementation.cmd_check(mock.Mock(adr_dir="architecture"))
            check_implementation.cmd_check(mock.Mock(adr_dir="architecture"))
        self.assertEqual(codes, [0, 1])


if __name__ == "__main__":
    unittest.main()
