"""Unit tests for the aligned log table layout (ADR-0016)."""

import sys
import unittest
from unittest import mock

from .helpers import load_run_pipeline


class TableFormatTest(unittest.TestCase):
    """TableLayout column widths and the row assembly (ADR-0016)."""

    def test_role_width_covers_all_rendered_role_labels(self) -> None:
        # The static role column must fit every label rendered during a run:
        # the base roles, the reviewer roles (ADR-0017) and the legacy
        # planner fork labels. `[reviewer-comment]` is the widest — one char
        # wider than the widest fork label, so a width computed from the
        # forks alone would start the step column one char late on every
        # reviewer row.
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout()
        self.assertEqual(layout.role_width, 18)
        self.assertEqual(layout.role_width, len("[reviewer-comment]"))
        labels = (
            ("planner", "executor", "harness")
            + tuple(f"reviewer-{kind}" for kind in ("srp", "bugs", "review", "comment", "tests"))
            + tuple(f"planner#{kind}" for kind in ("srp", "bugs", "review", "comment", "tests"))
        )
        for label in labels:
            rendered = layout.role_field(label)
            # Fits the static width: the rendered field is exactly the
            # column (label + padding), never longer.
            self.assertEqual(rendered, f"[{label}]".ljust(18), label)

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
        # The role column is padded to 18 and the spinner column is drawn on
        # a TTY only.
        self.assertIn("[planner]" + " " * 9 + " ⠋ ", tty_row)
        self.assertNotIn("⠋", nontty_row)
        self.assertIn("[planner]" + " " * 9 + " [study 4/15]", nontty_row)
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

    def test_step_output_rows_renders_document_block(self) -> None:
        # ADR-0021: a marker-wrapped stdout renders as one announcement row
        # plus the document lines verbatim from the left margin; the marker
        # lines are consumed.
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(tty=False)
        result = {
            "status": "completed",
            "output": {
                "stdout": (
                    "MO-BLOCK-START:summary\n"
                    "# Summary\n"
                    "\n"
                    "- item one\n"
                    "long paragraph line\n"
                    "MO-BLOCK-END\n"
                ),
                "stderr": "",
            },
        }
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            rows = mod.step_output_rows(result, layout)
        self.assertEqual(len(rows), 5)
        self.assertTrue(rows[0].startswith("[07:51:37] [harness]"))
        self.assertIn("summary:", rows[0])
        self.assertEqual(rows[1], "# Summary")
        self.assertEqual(rows[2], "")
        self.assertEqual(rows[3], "- item one")
        self.assertEqual(rows[4], "long paragraph line")
        for row in rows:
            self.assertNotIn("MO-BLOCK", row)

    def test_step_output_rows_block_empty_label(self) -> None:
        # A begin marker without a label: the announcement row carries no
        # tail; the block content still prints verbatim.
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(tty=False)
        result = {
            "status": "completed",
            "output": {"stdout": "MO-BLOCK-START:\nline one\nMO-BLOCK-END\n", "stderr": ""},
        }
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            rows = mod.step_output_rows(result, layout)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("MO-BLOCK", rows[0])
        self.assertEqual(rows[1], "line one")

    def test_step_output_rows_torn_block_falls_back_to_rows(self) -> None:
        # A begin marker without a matching end marker (torn output) falls
        # back to the per-line rows, marker line included; never raises.
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(tty=False)
        result = {
            "status": "completed",
            "output": {"stdout": "MO-BLOCK-START:summary\nline one\n", "stderr": ""},
        }
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            rows = mod.step_output_rows(result, layout)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].startswith("[07:51:37] [harness]"))
        self.assertIn("MO-BLOCK-START:summary", rows[0])
        self.assertIn("line one", rows[1])

    def test_step_output_rows_block_stderr_keeps_err_prefix(self) -> None:
        # The block protocol applies to stdout only: stderr still renders
        # as an [err] row after the block.
        mod = load_run_pipeline()
        layout = mod.table_format.TableLayout(tty=False)
        result = {
            "status": "completed",
            "output": {
                "stdout": "MO-BLOCK-START:summary\nline one\nMO-BLOCK-END\n",
                "stderr": "boom",
            },
        }
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            rows = mod.step_output_rows(result, layout)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1], "line one")
        self.assertIn("[err] boom", rows[2])


if __name__ == "__main__":
    unittest.main()
