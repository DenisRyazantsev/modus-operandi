"""Unit tests for the show-file.sh step script (ADR-0011)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from spec_utils import REPO_ROOT

SCRIPT = REPO_ROOT / "pipeline_scripts" / "show-file.sh"


class ShowFileTest(unittest.TestCase):
    """show-file.sh prints the file relative to state_dir with the control
    characters stripped (except \\t and \\n), rejects paths escaping
    state_dir (exit 2) and reports read errors with exit 1."""

    def _run(self, state_dir: Path, file: str):
        return subprocess.run(
            ["bash", str(SCRIPT), str(state_dir), file],
            capture_output=True,
            text=True,
        )

    def test_prints_file_without_control_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            target = state / "tasks" / "current"
            target.mkdir(parents=True)
            (target / "study.md").write_text(
                "line1\nline2\twith tab\n\x1b[31mred\x1b[0m\r\n", encoding="utf-8"
            )
            result = self._run(state, "tasks/current/study.md")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("\x1b", result.stdout)
        self.assertNotIn("\r", result.stdout)
        self.assertIn("line1", result.stdout)
        self.assertIn("line2\twith tab", result.stdout)
        self.assertIn("red", result.stdout)

    def test_rejects_paths_escaping_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            for file in ("../etc/passwd", "tasks/../../etc/passwd", "..", "a/.."):
                result = self._run(state, file)
                self.assertEqual(result.returncode, 2, file)
                self.assertEqual(result.stdout, "", file)
                self.assertIn("escapes", result.stderr)

    def test_missing_file_returns_1_with_empty_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            result = self._run(state, "tasks/current/missing.md")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotEqual(result.stderr, "")

    def test_wrong_arity_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            result = subprocess.run(
                ["bash", str(SCRIPT), str(state)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
