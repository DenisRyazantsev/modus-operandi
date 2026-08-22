"""Unit tests for the timing of the victory sound across the run lifecycle."""

import io
import tempfile
import unittest
from typing import Any
from unittest import mock

from tests.env_sandbox import argv, cwd, stdin, stdout

from .helpers import FakeProc, load_run_pipeline, point_config_at


class SoundTimingTest(unittest.TestCase):
    """The sound fires at the gate opening, on success and on failure alike —
    the same notify() call, never a different signal."""

    def _run_main(
        self, mod: Any, tmp: str, lines: list[str], returncode: int = 0
    ) -> tuple[int, Any]:
        point_config_at(mod, tmp)
        # A non-TTY stdin keeps main() on the plain path (no pty, no
        # forwarding thread): these tests are about notify() timing, not the
        # pty plumbing (covered by FeedbackGateFlowTest).
        with (
            cwd(tmp),
            mock.patch("subprocess.Popen", return_value=FakeProc(lines, returncode)),
            argv(["run-pipeline.py", "adr-pipeline"]),
            stdout(io.StringIO()),
            stdin(io.StringIO()),
            mock.patch.object(mod, "notify") as notify,
        ):
            rc = mod.main()
        return rc, notify

    def test_gate_open_fires_notify(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify = self._run_main(mod, tmp, ["┌─ Gate ─────────", "Run ID: abc12345"], 0)
        self.assertEqual(rc, 0)
        self.assertEqual(notify.call_count, 2)  # gate open + successful finish

    def test_success_fires_notify(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify = self._run_main(mod, tmp, ["Run ID: abc12345"], 0)
        self.assertEqual(rc, 0)
        self.assertEqual(notify.call_count, 1)

    def test_failure_fires_notify(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify = self._run_main(mod, tmp, ["Run ID: abc12345"], 1)
        self.assertEqual(rc, 1)
        self.assertEqual(notify.call_count, 1)
