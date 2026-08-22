"""Unit tests for the workflow step ids and the N/M markers (ADR-0011)."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.env_sandbox import cwd, stdout

from .helpers import load_run_pipeline


class WorkflowStepIdsTest(unittest.TestCase):
    """workflow_step_ids resolves the workflow file (path or bare id) and
    returns the ordered top-level step ids; missing/unparseable input
    degrades to None and the markers then omit the N/M part."""

    def test_returns_top_level_step_ids_from_source_path(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.yml"
            path.write_text(
                "schema_version: '1.0'\nsteps:\n  - id: a\n  - id: b\n  - id: c\n",
                encoding="utf-8",
            )
            self.assertEqual(mod.workflow_step_ids(str(path)), ["a", "b", "c"])

    def test_resolves_bare_id_from_installed_config_dir(self) -> None:
        # The module copy lives in a temp dir (helpers.load_run_pipeline), so
        # its CONFIG_DIR already points at a writable temp location: the
        # workflow file is created there for real.
        mod = load_run_pipeline()
        assert mod.__file__ is not None
        config_dir = Path(mod.__file__).resolve().parent.parent.parent / "modus-operandi"
        config_dir.mkdir(parents=True)
        (config_dir / "task-pipeline.yml").write_text(
            "steps:\n  - id: a\n  - id: b\n", encoding="utf-8"
        )
        self.assertEqual(mod.workflow_step_ids("task-pipeline"), ["a", "b"])

    def test_missing_file_degrades_to_none(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp, cwd(tmp):
            self.assertIsNone(mod.workflow_step_ids("no-such-pipeline"))

    def test_unparseable_yaml_degrades_to_none(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.yml"
            path.write_text("steps: [\n", encoding="utf-8")
            self.assertIsNone(mod.workflow_step_ids(str(path)))

    def test_wrong_document_shape_degrades_to_none(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.yml"
            path.write_text("workflow: {}\n", encoding="utf-8")
            self.assertIsNone(mod.workflow_step_ids(str(path)))


class StepMarkerIndexTest(unittest.TestCase):
    """step_marker_index: the completed step's own position among the
    top-level steps (bug fix: the engine's current_step_index has usually
    already advanced to the next step when the result is polled)."""

    def test_finds_the_step_position(self) -> None:
        mod = load_run_pipeline()
        ids = ["study", "research", "write-adr", "save-adr"]
        self.assertEqual(mod.step_marker_index("study", ids), 0)
        self.assertEqual(mod.step_marker_index("write-adr", ids), 2)

    def test_loop_iteration_suffix_uses_the_parent_step(self) -> None:
        # The engine writes loop-iteration results with a suffixed id: the
        # marker shows the position of the parent top-level step.
        mod = load_run_pipeline()
        ids = ["study", "motivation-loop", "research"]
        self.assertEqual(mod.step_marker_index("motivation-loop:motivation-gate:2", ids), 1)

    def test_unknown_step_degrades_to_none(self) -> None:
        mod = load_run_pipeline()
        ids = ["study", "research"]
        self.assertIsNone(mod.step_marker_index("no-such-step", ids))

    def test_no_workflow_ids_degrades_to_none(self) -> None:
        mod = load_run_pipeline()
        self.assertIsNone(mod.step_marker_index("study", None))
        self.assertIsNone(mod.step_marker_index("study", []))


class StepMarkerTest(unittest.TestCase):
    """print_step_result renders the N/M part from the completed step's own
    0-based index (1-based for humans)."""

    def test_step_marker_includes_nm(self) -> None:
        mod = load_run_pipeline()
        captured = io.StringIO()
        with (
            stdout(captured),
            # print_step_result lives in display.py, so the timestamp patch
            # must target that module (not the entry module).
            mock.patch.object(mod.display, "stamp", return_value="07:51:37"),
        ):
            mod.print_step_result("study", {"status": "completed", "output": {"stdout": ""}}, 3, 15)
        self.assertIn("[07:51:37] --- step study (completed) [4/15]", captured.getvalue())

    def test_step_marker_without_progress(self) -> None:
        mod = load_run_pipeline()
        captured = io.StringIO()
        with stdout(captured):
            mod.print_step_result("study", {"status": "completed", "output": {"stdout": ""}})
        self.assertIn("--- step study (completed)", captured.getvalue())
        self.assertNotIn("]", captured.getvalue().split("(completed)")[1])


class FmtMinutesTest(unittest.TestCase):
    """fmt_minutes: whole minutes with an 'm' suffix, standard rounding,
    non-zero values under 30 seconds round up to 1m."""

    def test_rounding(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.fmt_minutes(0), "0m")
        self.assertEqual(mod.fmt_minutes(1), "1m")
        self.assertEqual(mod.fmt_minutes(29), "1m")
        self.assertEqual(mod.fmt_minutes(30), "1m")
        self.assertEqual(mod.fmt_minutes(59), "1m")
        self.assertEqual(mod.fmt_minutes(60), "1m")
        self.assertEqual(mod.fmt_minutes(90), "2m")
        self.assertEqual(mod.fmt_minutes(150), "3m")
        self.assertEqual(mod.fmt_minutes(6301), "105m")
        self.assertEqual(mod.fmt_minutes(-5), "0m")
