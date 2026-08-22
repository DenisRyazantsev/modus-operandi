"""Unit tests for the engine stdout line classifier and its echo policy.

ADR-0013: the wrapper echoes specify's stdout strictly in its own format.
The classifier predicates are pure string functions (like
is_gate_menu_opener); the _consume_output policy — drop the engine's
step-start/header lines, re-print errors and diagnostics in the
`[hh:mm:ss] [harness]` format, echo the gate menu and unknown lines
unchanged, and still parse the run id — is covered end-to-end through
main().
"""

import io
import tempfile
import unittest
from typing import Any
from unittest import mock

from tests.env_sandbox import argv, cwd, stdin, stdout

from .helpers import FakeProc, load_run_pipeline, point_config_at


class EngineLineClassifierTest(unittest.TestCase):
    """Pure predicates: step-start lines, one-time headers, errors."""

    def test_recognizes_step_start_lines(self) -> None:
        mod = load_run_pipeline()
        self.assertTrue(mod.is_engine_step_start("  ▸ [review-fix-loop:pending-kinds:1] shell …"))
        self.assertTrue(
            mod.is_engine_step_start("  ▸ [review-fix-loop:review-fan:1:check:N] fan-out …")
        )
        self.assertTrue(mod.is_engine_step_start("▸ [a] b"))

    def test_rejects_non_step_start_lines(self) -> None:
        mod = load_run_pipeline()
        self.assertFalse(mod.is_engine_step_start(""))
        self.assertFalse(mod.is_engine_step_start("writing the ADR..."))
        self.assertFalse(mod.is_engine_step_start("│ 1. approve"))

    def test_recognizes_one_time_headers(self) -> None:
        mod = load_run_pipeline()
        for line in (
            "Running workflow: adr-pipeline (abc)",
            "Version: 0.16.3",
            "Status: completed",
            "Run ID: abc12345",
        ):
            self.assertTrue(mod.is_engine_header(line), line)
        self.assertFalse(mod.is_engine_header("status: lowercase"))
        self.assertFalse(mod.is_engine_header(""))

    def test_recognizes_engine_errors_and_diagnostics(self) -> None:
        mod = load_run_pipeline()
        for line in ("Error: boom", "Workflow failed: nope", "Warning: careful"):
            self.assertTrue(mod.is_engine_error(line), line)
        self.assertFalse(mod.is_engine_error("error: not the engine"))
        self.assertFalse(mod.is_engine_error("│ 1. approve"))
        self.assertFalse(mod.is_engine_error(""))


class ConsumeOutputEchoPolicyTest(unittest.TestCase):
    """The echo policy through main() (ADR-0013): engine progress lines and
    one-time headers are not printed, errors and diagnostics are re-printed
    as `[hh:mm:ss] [harness] <line as-is>`, the run id is parsed BEFORE the
    filtering so the resume message still works, and unknown lines echo
    unchanged (fail-open)."""

    def _run_main(
        self, mod: Any, tmp: str, lines: list[str], returncode: int = 0
    ) -> tuple[int, io.StringIO]:
        point_config_at(mod, tmp)
        out = io.StringIO()
        with (
            cwd(tmp),
            mock.patch("subprocess.Popen", return_value=FakeProc(lines, returncode)),
            argv(["run-pipeline.py", "adr-pipeline"]),
            stdout(out),
            stdin(io.StringIO()),
        ):
            rc = mod.main()
        return rc, out

    def test_engine_progress_and_headers_are_not_echoed(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._run_main(
                mod,
                tmp,
                [
                    "Running workflow: adr-pipeline (abc)",
                    "Version: 0.16.3",
                    "  ▸ [review-fix-loop:pending-kinds:1] shell …",
                    "  ▸ [review-fix-loop:review-fan:1] fan-out …",
                    "Status: completed",
                    "Run ID: abc12345",
                ],
                0,
            )
        self.assertEqual(rc, 0)
        text = out.getvalue()
        for needle in (
            "▸",
            "Running workflow:",
            "Version:",
            "Status: completed",
            "Run ID: abc12345",
        ):
            self.assertNotIn(needle, text)

    def test_engine_errors_echo_in_harness_format(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._run_main(
                mod,
                tmp,
                ["Error: boom", "Workflow failed: nope", "Warning: careful", "Run ID: abc12345"],
                1,
            )
        self.assertEqual(rc, 1)
        text = out.getvalue()
        for needle in (
            "[harness] Error: boom",
            "[harness] Workflow failed: nope",
            "[harness] Warning: careful",
        ):
            self.assertIn(needle, text)
        # The run id was parsed before the filtering: the resume message
        # still works even though the "Run ID:" line was not echoed.
        self.assertIn("resume with: specify workflow resume abc12345", text)
        self.assertNotIn("Run ID: abc12345", text)

    def test_unknown_lines_echo_unchanged(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._run_main(
                mod, tmp, ["a line the engine never printed before", "Run ID: abc12345"], 0
            )
        self.assertEqual(rc, 0)
        text = out.getvalue()
        # Fail-open: an unrecognized line still echoes (timestamped), so a
        # future engine line is never lost silently.
        self.assertIn("a line the engine never printed before", text)
        self.assertNotIn("Run ID: abc12345", text)
