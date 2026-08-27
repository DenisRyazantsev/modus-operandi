"""Unit tests for the show-file.sh step script (ADR-0011)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SCRIPT = REPO_ROOT / "src/modus_operandi/data/pipeline_scripts" / "show-file.sh"


class ShowFileTest(unittest.TestCase):
    """show-file.sh prints the file relative to state_dir with the control
    characters stripped (except \\t and \\n), rejects paths escaping
    state_dir (exit 2) and reports read errors with exit 1."""

    def _run(self, state_dir: Path, file: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), str(state_dir), file],
            capture_output=True,
            text=True,
        )

    def _run_block(
        self, state_dir: Path, file: str, label: str = "summary"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), str(state_dir), file, "--block", label],
            capture_output=True,
            text=True,
        )

    def test_prints_file_without_control_characters(self) -> None:
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

    def test_rejects_paths_escaping_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            for file in ("../etc/passwd", "tasks/../../etc/passwd", "..", "a/.."):
                result = self._run(state, file)
                self.assertEqual(result.returncode, 2, file)
                self.assertEqual(result.stdout, "", file)
                self.assertIn("escapes", result.stderr)

    def test_missing_file_returns_1_with_empty_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            result = self._run(state, "tasks/current/missing.md")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotEqual(result.stderr, "")

    def test_wrong_arity_returns_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            result = subprocess.run(
                ["bash", str(SCRIPT), str(state)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)

    def test_block_mode_wraps_output_in_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            target = state / "tasks" / "current"
            target.mkdir(parents=True)
            (target / "summary.md").write_text("# Summary\n\n- item one\n", encoding="utf-8")
            result = self._run_block(state, "tasks/current/summary.md")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "MO-BLOCK-START:summary\n# Summary\n\n- item one\nMO-BLOCK-END\n",
        )

    def test_block_mode_file_without_trailing_newline_keeps_marker_fresh(self) -> None:
        # A file that does not end with `\n` must not glue MO-BLOCK-END to
        # its last content line: the end marker starts a fresh line, and
        # no extra blank line appears when the file already ends with `\n`.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            target = state / "tasks" / "current"
            target.mkdir(parents=True)
            (target / "summary.md").write_text("# Summary\n\n- item one", encoding="utf-8")
            result = self._run_block(state, "tasks/current/summary.md")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "MO-BLOCK-START:summary\n# Summary\n\n- item one\nMO-BLOCK-END\n",
        )

    def test_block_mode_missing_file_prints_no_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            result = self._run_block(state, "tasks/current/missing.md")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotEqual(result.stderr, "")
