"""Unit tests for the live status lines (live_lines.py, ADR-0011)."""

import sys
import unittest
from unittest import mock

from .helpers import load_run_pipeline


def _step_finish(input=10, output=20, reasoning=30, cache_read=40, cost=0.5):
    return {
        "type": "step_finish",
        "part": {
            "type": "step-finish",
            "tokens": {
                "input": input,
                "output": output,
                "reasoning": reasoning,
                "cache": {"read": cache_read, "write": 0},
            },
            "cost": cost,
        },
    }


class LiveLinesTest(unittest.TestCase):
    """The line format, the per-process accumulators, the fixation on step
    completion and the non-TTY one-line-per-event behavior."""

    def test_line_format_with_step_and_progress(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        with mock.patch.object(
            sys.modules["live_lines"], "stamp", return_value="07:51:37"
        ):
            line = live.add_event("planner", "", _step_finish())
            # TTY: the event only updates the block.
            self.assertIsNone(line)
            block = live.block()
        self.assertEqual(len(block), 1)
        self.assertEqual(
            block[0],
            "[07:51:37] [planner] [study 4/15] cache 40 · reasoning 30 · "
            "input 10 · output 20 · price $0.50",
        )

    def test_line_without_progress_omits_nm(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", _step_finish())
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[study]", block[0])
        self.assertNotIn("4/15", block[0])

    def test_line_without_step_omits_step_part(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.set_step("", 0)
        live.add_event("planner", "", _step_finish())
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[planner]", block[0])
        self.assertIn("[planner] cache", block[0])

    def test_unreadable_index_omits_nm_not_crash(self):
        # A non-numeric/absent engine index (set_step(None)) must degrade to
        # a line without N/M, like a missing workflow file (bug fix).
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", None)
        live.add_event("planner", "", _step_finish())
        block = live.block()
        self.assertIn("[study]", block[0])
        self.assertNotIn("15", block[0])

    def test_negative_index_is_clamped_to_zero(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", -3)
        live.add_event("planner", "", _step_finish())
        block = live.block()
        self.assertIn("[study 1/15]", block[0])

    def test_accumulates_across_events_and_steps(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", _step_finish(input=10, cache_read=40, cost=0.5))
        live.add_event("planner", "", _step_finish(input=5, cache_read=60, cost=0.25))
        fixed = live.fix_all()
        self.assertEqual(len(fixed), 1)
        self.assertIn("cache 100", fixed[0])
        self.assertIn("input 15", fixed[0])
        self.assertIn("price $0.75", fixed[0])
        # The next step opens a new line; the sums continue.
        live.set_step("research", 4)
        live.add_event("planner", "", _step_finish(input=1, cache_read=2, cost=0.01))
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[research 5/15]", block[0])
        self.assertIn("cache 102", block[0])
        self.assertIn("price $0.76", block[0])

    def test_fix_all_clears_the_block(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", _step_finish())
        self.assertEqual(len(live.block()), 1)
        self.assertEqual(len(live.fix_all()), 1)
        self.assertEqual(live.block(), [])

    def test_fork_label_and_separate_accumulator(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("review-fan", 10)
        live.add_event("planner", "4242", _step_finish(input=1, cache_read=2, cost=0.01))
        live.add_event("planner", "4243", _step_finish(input=3, cache_read=4, cost=0.02))
        block = live.block()
        self.assertEqual(len(block), 2)
        self.assertIn("[planner#4242]", block[0])
        self.assertIn("cache 2", block[0])
        self.assertIn("[planner#4243]", block[1])
        self.assertIn("cache 4", block[1])

    def test_non_step_finish_events_ignored(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.add_event(
            "planner", "", {"type": "step_start", "part": {"type": "step-start"}}
        )
        live.add_event("planner", "", {"type": "text", "part": {"type": "text", "text": "x"}})
        live.add_event("planner", "", None)
        live.add_event("planner", "", "not a dict")
        self.assertEqual(live.block(), [])

    def test_malformed_event_fields_are_skipped_not_crash(self):
        # A step_finish with non-numeric tokens/cost or non-dict subobjects
        # must be skipped whole: one broken event must not raise inside the
        # monitor thread and kill the live status (bug fix).
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        malformed = [
            {"type": "step_finish", "part": {"tokens": {"input": "abc"}}},
            {"type": "step_finish", "part": {"tokens": {"input": 1, "cache": "x"}}},
            {"type": "step_finish", "part": {"cost": "oops"}},
            {"type": "step_finish", "part": {"tokens": [1, 2]}},
            {"type": "step_finish", "part": "not a dict"},
        ]
        for event in malformed:
            live.add_event("planner", "", event)
        self.assertEqual(live.block(), [])
        # A valid event afterwards still accumulates.
        live.add_event("planner", "", _step_finish(input=10, cache_read=40, cost=0.5))
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("input 10", block[0])

    def test_thousands_separators_in_counts(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.add_event("planner", "", _step_finish(input=321213, cache_read=9032013))
        block = live.block()
        self.assertIn("cache 9 032 013", block[0])
        self.assertIn("input 321 213", block[0])

    def test_non_tty_returns_one_line_per_step_finish(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=False)
        live.set_step("study", 3)
        with mock.patch.object(
            sys.modules["live_lines"], "stamp", return_value="07:51:37"
        ):
            line = live.add_event("planner", "", _step_finish())
        self.assertIsNotNone(line)
        self.assertEqual(
            line,
            "[07:51:37] [planner] [study 4/15] cache 40 · reasoning 30 · "
            "input 10 · output 20 · price $0.50",
        )
        # No block and no fixed lines in non-TTY mode: every event already
        # printed its own plain line.
        self.assertEqual(live.block(), [])
        self.assertEqual(live.fix_all(), [])

    def test_non_tty_sums_continue_across_events(self):
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=False)
        first = live.add_event("planner", "", _step_finish(input=10, cache_read=40))
        second = live.add_event("planner", "", _step_finish(input=5, cache_read=60))
        self.assertIn("input 10", first)
        self.assertIn("input 15", second)
        self.assertIn("cache 100", second)
