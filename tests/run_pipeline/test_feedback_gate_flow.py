"""Unit tests for the full main() feedback-gate flow."""

import contextlib
import io
import json
import os
import pty
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.env_sandbox import argv, cwd, stdout

from .helpers import FakeProc, load_run_pipeline, point_config_at


class FeedbackGateFlowTest(unittest.TestCase):
    """main() recognizes the ADR revise feedback gate: the editor opens and
    no victory sound is played (both for the editor path and the manual
    fallback); regular gates still notify()."""

    def _run_main(
        self, mod: Any, tmp: str, step_id: str, editor_result: Any
    ) -> tuple[int, Any, Any]:
        point_config_at(mod, tmp)
        state_root = Path(tmp) / ".specify"
        run_dir = state_root / "workflows" / "runs" / "abc12345"
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text(
            json.dumps({"current_step_id": step_id}), encoding="utf-8"
        )
        real_master, real_slave = pty.openpty()
        # The run dir exists before main() starts; the wrapper snapshots
        # prior runs BEFORE the workflow starts, so the first existing_run_ids
        # call must see nothing (making abc12345 look like it appeared during
        # the run) and later calls must find it.
        state = {"calls": 0}

        def fake_existing(state_dir: Any) -> set[str]:
            state["calls"] += 1
            return {"abc12345"} if state["calls"] > 1 else set()

        try:
            with (
                cwd(tmp),
                mock.patch("sys.stdin", mock.Mock(isatty=lambda: True)),
                mock.patch("pty.openpty", return_value=(real_master, real_slave)),
                mock.patch(
                    "subprocess.Popen",
                    return_value=FakeProc(["┌─ Gate ─────────", "Run ID: abc12345"], 0, env={}),
                ),
                argv(["run-pipeline.py", "adr-pipeline"]),
                stdout(io.StringIO()),
                mock.patch.object(mod, "notify") as notify,
                mock.patch.object(
                    mod, "open_feedback_editor", return_value=editor_result
                ) as editor,
                mock.patch.object(mod, "forward_terminal_input"),
                # main() resolves existing_run_ids in the entry module; the
                # discoverer resolves its own copy in run_id_discoverer.py.
                mock.patch.object(mod, "existing_run_ids", side_effect=fake_existing),
                mock.patch.object(
                    mod.run_id_discoverer, "existing_run_ids", side_effect=fake_existing
                ),
            ):
                rc = mod.main()
        finally:
            for fd in (real_master, real_slave):
                with contextlib.suppress(OSError):
                    os.close(fd)
        return rc, notify, editor

    def test_feedback_gate_opens_editor_without_sound(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify, editor = self._run_main(mod, tmp, "adr-feedback-gate", editor_result=True)
        self.assertEqual(rc, 0)
        editor.assert_called_once()
        state_dir, pause, master_fd, step_id = editor.call_args.args
        self.assertEqual(state_dir, ".workflow")
        self.assertEqual(step_id, "adr-feedback-gate")
        self.assertIsNotNone(master_fd)
        self.assertIsInstance(pause, threading.Event)
        # No victory sound for the feedback gate itself: only the final
        # success signal fires.
        self.assertEqual(notify.call_count, 1)

    def test_feedback_gate_loop_iteration_without_sound(self) -> None:
        # The loop-iteration form of the feedback gate id is recognized too.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify, editor = self._run_main(
                mod, tmp, "adr-loop:adr-feedback-gate:1", editor_result=True
            )
        self.assertEqual(rc, 0)
        editor.assert_called_once()
        self.assertEqual(editor.call_args.args[3], "adr-loop:adr-feedback-gate:1")
        self.assertEqual(notify.call_count, 1)

    def test_feedback_gate_fallback_without_sound(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify, editor = self._run_main(mod, tmp, "adr-feedback-gate", editor_result=False)
        self.assertEqual(rc, 0)
        editor.assert_called_once()
        self.assertEqual(notify.call_count, 1)

    def test_regular_gate_still_notifies(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, notify, editor = self._run_main(mod, tmp, "adr-gate", editor_result=True)
        self.assertEqual(rc, 0)
        editor.assert_not_called()
        # gate open + successful finish
        self.assertEqual(notify.call_count, 2)
