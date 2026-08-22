"""Unit tests for role-label alignment in the console output."""

import io
import unittest
from unittest import mock

from .helpers import load_run_pipeline


class LogAlignmentTest(unittest.TestCase):
    """Role labels are padded to the longest role name so the text after
    "[role] " starts at the same column for planner and executor."""

    def test_role_label_pads_to_longest_role(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.role_label("planner"), "[planner ]")
        self.assertEqual(mod.role_label("executor"), "[executor]")

    def test_print_log_event_aligns_text_start(self) -> None:
        mod = load_run_pipeline()
        captured = io.StringIO()
        with (
            mock.patch("sys.stdout", captured),
            # print_log_event lives in _run_pipeline_common, so the timestamp
            # patch must target that module (not the entry module).
            mock.patch.object(mod._run_pipeline_common, "stamp", return_value="07:51:37"),
        ):
            mod.print_log_event("planner", "I verified")
            mod.print_log_event("executor", "SRP-review")
        lines = captured.getvalue().splitlines()
        self.assertTrue(lines[0].endswith("I verified"))
        self.assertTrue(lines[1].endswith("SRP-review"))
        # The text starts at the same column on both lines.
        self.assertEqual(lines[0].index("I verified"), lines[1].index("SRP-review"))
        self.assertTrue(lines[0].startswith("[07:51:37] [planner ] "))
        self.assertTrue(lines[1].startswith("[07:51:37] [executor] "))
