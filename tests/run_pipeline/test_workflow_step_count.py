"""Unit tests for the workflow step-id lists (ADR-0011, ADR-0016): the
top-level ids and the full collection (nested steps included) that sizes
the aligned step column."""

import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import cwd

from .helpers import load_run_pipeline


class WorkflowStepIdsTest(unittest.TestCase):
    """workflow_step_ids resolves the workflow file (path or bare id) and
    returns the ordered top-level step ids; missing/unparseable input
    degrades to None."""

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


class WorkflowAllStepIdsTest(unittest.TestCase):
    """workflow_all_step_ids collects every step id of the workflow file —
    nested steps included (do-while `steps:`, if `then:`/`else:`, fan-out
    `step:`) — for the aligned step column (ADR-0016); missing/unparseable
    input degrades to None."""

    def test_collects_nested_ids(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.yml"
            path.write_text(
                "schema_version: '1.0'\n"
                "steps:\n"
                "  - id: study\n"
                "  - id: motivation-loop\n"
                "    steps:\n"
                "      - id: motivation-gate\n"
                "        then:\n"
                "          - id: motivation-revise\n"
                "        else:\n"
                "          - id: motivation-else\n"
                "      - id: motivation-check\n"
                "  - id: write-adr\n"
                "    step:\n"
                "      id: executor-questions\n",
                encoding="utf-8",
            )
            self.assertEqual(
                mod.workflow_all_step_ids(str(path)),
                [
                    "study",
                    "motivation-loop",
                    "motivation-gate",
                    "motivation-revise",
                    "motivation-else",
                    "motivation-check",
                    "write-adr",
                    "executor-questions",
                ],
            )

    def test_missing_file_degrades_to_none(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp, cwd(tmp):
            self.assertIsNone(mod.workflow_all_step_ids("no-such-pipeline"))

    def test_unparseable_yaml_degrades_to_none(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.yml"
            path.write_text("steps: [\n", encoding="utf-8")
            self.assertIsNone(mod.workflow_all_step_ids(str(path)))

    def test_resolves_bare_id_from_installed_config_dir(self) -> None:
        # The same resolution as workflow_step_ids: a bare id is looked up
        # in the installed config dir (the module copy's CONFIG_DIR in
        # tests), nested ids included.
        mod = load_run_pipeline()
        assert mod.__file__ is not None
        config_dir = Path(mod.__file__).resolve().parent.parent.parent / "modus-operandi"
        config_dir.mkdir(parents=True)
        (config_dir / "task-pipeline.yml").write_text(
            "steps:\n  - id: a\n    steps:\n      - id: a1\n  - id: b\n",
            encoding="utf-8",
        )
        self.assertEqual(mod.workflow_all_step_ids("task-pipeline"), ["a", "a1", "b"])


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
