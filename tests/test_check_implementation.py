"""Tests for pipeline_scripts/check_implementation.py (implement guard).

The guard is exercised against a real git repository built in a temp
directory: real commits, real working-tree changes and real git errors.
No run_git call is stubbed — only the working directory and the git
identity are controlled.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import cwd

REPO_ROOT = Path(__file__).resolve().parent.parent

_PS_DIR = REPO_ROOT / "src" / "modus_operandi" / "data" / "pipeline_scripts"
_SCRIPT = _PS_DIR / "check_implementation.py"

_SPEC = importlib.util.spec_from_file_location(
    "check_implementation", _PS_DIR / "check_implementation.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_implementation = importlib.util.module_from_spec(_SPEC)
sys.modules["check_implementation"] = check_implementation
_SPEC.loader.exec_module(check_implementation)

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


class RealGitCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.assertEqual(self._git("init", "-q").returncode, 0)

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env={**os.environ, **_GIT_ENV},
            check=False,
        )

    def _commit(self, filename: str, content: str = "x\n") -> None:
        path = self.repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._git("add", filename)
        self.assertEqual(self._git("commit", "-m", f"add {filename}").returncode, 0)


class HasChangesTest(RealGitCase):
    def test_no_changes(self) -> None:
        self._commit("a.txt")
        with cwd(self.repo):
            self.assertEqual(
                check_implementation.has_changes("architecture"), (False, "no changes")
            )

    def test_tracked_changes(self) -> None:
        # git diff --quiet exits 1 when tracked files differ.
        self._commit("a.txt")
        (self.repo / "a.txt").write_text("modified\n", encoding="utf-8")
        with cwd(self.repo):
            self.assertEqual(
                check_implementation.has_changes("architecture"),
                (True, "tracked files modified"),
            )

    def test_untracked_new_file(self) -> None:
        self._commit("a.txt")
        (self.repo / "new.py").write_text("x\n", encoding="utf-8")
        with cwd(self.repo):
            changes, summary = check_implementation.has_changes("architecture")
        self.assertTrue(changes)
        self.assertIn("new file(s)", summary)

    def test_only_saved_adr_is_not_a_change(self) -> None:
        # The pipeline's own saved ADR (architecture/ADR-*.md) is untracked
        # but is not executor work; without the exclusion an empty implement
        # would always "pass".
        self._commit("a.txt")
        adr = self.repo / "architecture" / "ADR-0007-executor-guard.md"
        adr.parent.mkdir(parents=True, exist_ok=True)
        adr.write_text("x\n", encoding="utf-8")
        with cwd(self.repo):
            self.assertEqual(
                check_implementation.has_changes("architecture"), (False, "no changes")
            )

    def test_saved_adr_plus_code_file_counts(self) -> None:
        self._commit("a.txt")
        adr = self.repo / "architecture" / "ADR-0007-x.md"
        adr.parent.mkdir(parents=True, exist_ok=True)
        adr.write_text("x\n", encoding="utf-8")
        (self.repo / "new.py").write_text("x\n", encoding="utf-8")
        with cwd(self.repo):
            self.assertTrue(check_implementation.has_changes("architecture")[0])

    def test_diff_error_is_reported(self) -> None:
        # No git repository at all: the real git diff fails with 128.
        with cwd(self.repo):
            changes, summary = check_implementation.has_changes("architecture")
        self.assertFalse(changes)
        self.assertIn("git diff failed", summary)

    def test_custom_adr_dir_exclusion(self) -> None:
        self._commit("a.txt")
        adr = self.repo / "docs" / "ADR-0001-x.md"
        adr.parent.mkdir(parents=True, exist_ok=True)
        adr.write_text("x\n", encoding="utf-8")
        with cwd(self.repo):
            self.assertEqual(check_implementation.has_changes("docs"), (False, "no changes"))


class ExitCodeTest(RealGitCase):
    def test_changes_exit_zero_no_changes_exit_one(self) -> None:
        # The script runs as a real subprocess; the exit code is real.
        self._commit("a.txt")
        (self.repo / "new.py").write_text("x\n", encoding="utf-8")
        with cwd(self.repo):
            changed = subprocess.run(
                [sys.executable, str(_SCRIPT), "check", "architecture"],
                capture_output=True,
                text=True,
            )
        (self.repo / "new.py").unlink()
        with cwd(self.repo):
            unchanged = subprocess.run(
                [sys.executable, str(_SCRIPT), "check", "architecture"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(changed.returncode, 0)
        self.assertIn("implementation check:", changed.stdout)
        self.assertEqual(unchanged.returncode, 1)
