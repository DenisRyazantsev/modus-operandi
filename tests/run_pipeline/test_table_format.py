"""Unit tests for the aligned log table layout (ADR-0016)."""

import sys
import unittest
from unittest import mock

from .helpers import load_run_pipeline


class TableFormatTest(unittest.TestCase):
    """TableLayout column widths and the row assembly (ADR-0016)."""

    def test_role_width_covers_fork_labels(self) -> None:
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout()
        self.assertEqual(layout.role_width, 17)
        self.assertEqual(layout.role_width, len("[planner#comment]"))

    def test_step_width_for_uses_widest_bracket_with_nm_allowance(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(
            mod.step_width_for(["study", "executor-questions-loop:executor-questions"], 15),
            len("[executor-questions-loop:executor-questions 15/15]"),
        )

    def test_step_width_for_degrades_to_zero(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.step_width_for([], 15), 0)
        self.assertEqual(mod.step_width_for(["a"], None), 0)
        self.assertEqual(mod.step_width_for(None, 15), 0)

    def test_step_field_widens_once_and_pads_later(self) -> None:
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(step_width=0)
        self.assertEqual(layout.step_field("study", 3, 15), "[study 4/15]")
        self.assertEqual(layout.step_width, 12)
        self.assertEqual(layout.step_field("x", 0, 15), "[x 1/15]    ")
        self.assertEqual(layout.step_width, 12)

    def test_step_field_without_step_pads_empty_column(self) -> None:
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(step_width=0)
        layout.step_field("study", 3, 15)  # widens the column to 12
        self.assertEqual(layout.step_field("", None, None), " " * 12)
        self.assertEqual(layout.empty_step(), " " * 12)

    def test_tokens_right_align_and_grow_per_column(self) -> None:
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout()
        self.assertEqual(layout.tokens([("cache", "3 510 016")]), "cache 3 510 016")
        # cache is padded to the 9-char width of "3 510 016"; input has its
        # own column (width 2), independent of cache.
        self.assertEqual(
            layout.tokens([("cache", "218 496"), ("input", "10")]),
            "cache   218 496 · input 10",
        )

    def test_row_tty_has_spin_column_nontty_does_not(self) -> None:
        mod = load_run_pipeline()
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            tty_row = mod.table_format.TableLayout(tty=True).row(
                "planner", "⠋", "[study 4/15]", "cache 10"
            )
            nontty_row = mod.table_format.TableLayout(tty=False).row(
                "planner", "⠋", "[study 4/15]", "cache 10"
            )
        # The role column is padded to 17 and the spinner column is drawn on
        # a TTY only.
        self.assertIn("[planner]" + " " * 8 + " ⠋ ", tty_row)
        self.assertNotIn("⠋", nontty_row)
        self.assertIn("[planner]" + " " * 8 + " [study 4/15]", nontty_row)
        for line in (tty_row, nontty_row):
            self.assertEqual(line, line.rstrip())

    def test_step_output_rows_drops_session_and_empty_lines(self) -> None:
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(tty=False)
        result = {
            "status": "completed",
            "output": {"stdout": "SESSION:ses_abc\n\nsaved adr: architecture/ADR-0016.md\n"},
        }
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            rows = mod.step_output_rows(result, layout)
        self.assertEqual(len(rows), 1)
        self.assertIn("saved adr: architecture/ADR-0016.md", rows[0])
        self.assertNotIn("SESSION", rows[0])
        self.assertTrue(rows[0].startswith("[07:51:37] [harness]"))

    def test_step_output_rows_stderr_gets_err_prefix(self) -> None:
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(tty=False)
        result = {"status": "failed", "output": {"stdout": "", "stderr": "boom"}}
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            rows = mod.step_output_rows(result, layout)
        self.assertEqual(len(rows), 1)
        self.assertIn("[err] boom", rows[0])
        self.assertIn("[harness]", rows[0])

    def test_step_output_rows_uses_empty_step_column(self) -> None:
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(tty=False)
        result = {"status": "completed", "output": {"stdout": "saved adr: x\n"}}
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            rows = mod.step_output_rows(result, layout)
        # No step bracket after the role label: the step column stays empty
        # and the tail text follows right after the role padding.
        role_end = rows[0].index("[harness]") + len("[harness]")
        self.assertNotIn("[", rows[0][role_end:])
        self.assertIn("saved adr: x", rows[0])

    def test_step_output_rows_non_str_fields_do_not_raise(self) -> None:
        # Regression (bug fix): the `output` container is guarded against a
        # non-dict, but the stdout/stderr VALUES can also be non-strings in
        # a torn or hand-edited state.json — a raw AttributeError there
        # would propagate out of _poll_once and silently kill the monitor
        # thread (the live status stops updating for the rest of the run).
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(tty=False)
        result = {"status": "completed", "output": {"stdout": 123, "stderr": {"x": 1}}}
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            rows = mod.step_output_rows(result, layout)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
