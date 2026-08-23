"""Unit tests for the live status lines (live_lines.py, ADR-0011/0012)."""

import re
import sys
import unittest
from unittest import mock

from .helpers import load_run_pipeline


def _step_finish(
    input: int = 10,
    output: int = 20,
    reasoning: int = 30,
    cache_read: int = 40,
    cost: float = 0.5,
) -> dict[str, object]:
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
    """The line format (spinner + optional token section), the per-process
    accumulators, the harness line before the step's first agent event, the
    fixation on step completion, the cursor usage forms and the non-TTY
    behavior (ADR-0012)."""

    def test_line_format_with_step_and_progress(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            line = live.add_event("planner", "", _step_finish())
            # TTY: the event only updates the block.
            self.assertIsNone(line)
            block = live.block()
        self.assertEqual(len(block), 1)
        self.assertEqual(
            block[0],
            "[07:51:37] [planner]          \u280b [study 4/15] cache 40 · reasoning 30 · "
            "input 10 · output 20 · price $0.50",
        )

    def test_line_without_progress_omits_nm(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", _step_finish())
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[study]", block[0])
        self.assertNotIn("4/15", block[0])

    def test_line_without_step_omits_step_part(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.set_step("", 0)
        live.add_event("planner", "", _step_finish())
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[planner]", block[0])
        self.assertIn("cache 40", block[0])

    def test_unreadable_index_omits_nm_not_crash(self) -> None:
        # A non-numeric/absent engine index (set_step(None)) must degrade to
        # a line without N/M, like a missing workflow file (bug fix).
        # The N/M absence is asserted by shape (not by a bare digit string,
        # which the timestamp could contain, e.g. ":15:").
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", None)
        live.add_event("planner", "", _step_finish())
        block = live.block()
        self.assertIn("[study]", block[0])
        self.assertNotRegex(block[0], r"\[study \d+/15\]")

    def test_negative_index_is_clamped_to_zero(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", -3)
        live.add_event("planner", "", _step_finish())
        block = live.block()
        self.assertIn("[study 1/15]", block[0])

    def test_accumulates_across_events_and_steps(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", _step_finish(input=10, cache_read=40, cost=0.5))
        live.add_event("planner", "", _step_finish(input=5, cache_read=60, cost=0.25))
        fixed = live.pin_all()
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

    def test_pin_all_fixes_and_reopens_the_block(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", _step_finish())
        self.assertEqual(len(live.block()), 1)
        self.assertEqual(len(live.pin_all()), 1)
        # The block reopens with the harness line (the step has no events
        # anymore) — never with a stale process line.
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[harness]", block[0])
        self.assertNotIn("[planner]", block[0])

    def test_fork_label_and_separate_accumulator(self) -> None:
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

    def test_any_event_activates_the_process(self) -> None:
        # The process is active from the first ANY event (the current cursor
        # emits no step_start): a token-less event opens the process line
        # without a token section (ADR-0012).
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", {"type": "step_start", "part": {"type": "step-start"}})
        live.add_event("planner", "", {"type": "text", "part": {"type": "text", "text": "x"}})
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[planner]", block[0])
        self.assertNotIn("cache", block[0])
        self.assertNotIn("price", block[0])
        # A valid usage event afterwards accumulates.
        live.add_event("planner", "", _step_finish(input=10, cache_read=40, cost=0.5))
        self.assertIn("input 10", live.block()[0])

    def test_non_dict_events_are_skipped_not_crash(self) -> None:
        # Non-dict events are malformed and skipped whole: no activation.
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.add_event("planner", "", None)
        live.add_event("planner", "", "not a dict")
        live.add_event("planner", "", 42)
        self.assertEqual(live.block(), [])

    def test_malformed_event_fields_are_skipped_not_crash(self) -> None:
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

    def test_thousands_separators_in_counts(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.add_event("planner", "", _step_finish(input=321213, cache_read=9032013))
        block = live.block()
        self.assertIn("cache 9 032 013", block[0])
        self.assertIn("input 321 213", block[0])

    def test_non_tty_returns_one_line_per_step_finish(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=False)
        live.set_step("study", 3)
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            line = live.add_event("planner", "", _step_finish())
        self.assertIsNotNone(line)
        self.assertEqual(
            line,
            "[07:51:37] [planner]          [study 4/15] cache 40 · reasoning 30 · "
            "input 10 · output 20 · price $0.50",
        )
        # No block and no fixed lines in non-TTY mode: every event already
        # printed its own plain line.
        self.assertEqual(live.block(), [])
        self.assertEqual(live.pin_all(), [])

    def test_non_tty_sums_continue_across_events(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=False)
        first = live.add_event("planner", "", _step_finish(input=10, cache_read=40))
        second = live.add_event("planner", "", _step_finish(input=5, cache_read=60))
        self.assertIn("input 10", first)
        self.assertIn("input 15", second)
        self.assertIn("cache 100", second)

    def test_non_tty_event_without_usage_prints_nothing(self) -> None:
        # On a non-TTY only events WITH usage print a line: one plain line
        # per agent turn (ADR-0012).
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=False)
        self.assertIsNone(live.add_event("planner", "", {"type": "text", "part": {"type": "text"}}))
        line = live.add_event("planner", "", _step_finish())
        self.assertIsNotNone(line)

    def test_non_tty_cursor_usage_event_prints_one_line(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=False, backend="cursor")
        line = live.add_event(
            "planner",
            "",
            {"type": "result", "usage": {"inputTokens": 10, "outputTokens": 5}},
        )
        self.assertIsNotNone(line)
        self.assertIn("input 10", line)
        self.assertNotIn("price", line)

    def test_non_tty_reopens_line_with_current_step_label_after_fix(self) -> None:
        # Regression (bug fix): pin_all on a non-TTY must clear _active, so
        # the next event re-opens the process line and re-captures the step
        # label — a stale _active would keep every later line labelled with
        # the completed step forever.
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=3, tty=False)
        live.set_step("study", 0)
        live.add_event("planner", "", _step_finish())
        live.pin_all("study")
        live.set_step("research", 1)
        line = live.add_event("planner", "", _step_finish())
        self.assertIsNotNone(line)
        self.assertIn("[research 2/3]", line)
        self.assertNotIn("[study", line)


class SpinnerTest(unittest.TestCase):
    """The spinner (ADR-0012/0013): one-column frames, chosen from the
    elapsed time (rich-style time-based cadence of 0.25 s), placed between
    the role label and the step part."""

    def test_frames_are_single_column_cells(self) -> None:
        for frame in sys.modules["live_lines"].SPINNER_FRAMES:
            self.assertEqual(len(frame), 1)

    def test_harness_line_contains_spinner_between_label_and_step(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        line = live.block()[0]
        m = re.search(r"\[harness\] +(\S) \[study 4/15\]", line)
        assert m is not None
        self.assertIn(m.group(1), sys.modules["live_lines"].SPINNER_FRAMES)

    def test_process_line_spinner_between_label_and_step(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", _step_finish())
        m = re.search(r"\[planner\] +(\S) \[study 4/15\]", live.block()[0])
        assert m is not None
        self.assertIn(m.group(1), sys.modules["live_lines"].SPINNER_FRAMES)

    def test_frame_advances_every_heartbeat_by_elapsed_time(self) -> None:
        # ADR-0013: the frame is a function of the elapsed time since
        # LiveLines was created (the rich time-based principle), so it
        # advances every HEARTBEAT_SECONDS (0.25 s) and a skipped monitor
        # tick advances several frames at once — the 4 fps cadence never
        # drifts. The first monotonic() value is consumed by __init__ as
        # the time origin.
        mod = load_run_pipeline()
        spinner = sys.modules["live_lines"].SPINNER_FRAMES
        with mock.patch.object(
            sys.modules["live_lines"].time,
            "monotonic",
            side_effect=[10.0, 10.0, 10.2, 10.25, 10.5, 10.75, 11.0],
        ):
            live = mod.LiveLines(tty=True)
            live.set_step("study", 3)
            shown = []
            for _ in range(6):
                m = re.search(r"\[harness\] +(\S) \[study", live.block()[0])
                assert m is not None
                shown.append(spinner.index(m.group(1)))
        # < 0.25 s: same frame; each 0.25 s boundary advances exactly one.
        self.assertEqual(shown, [0, 0, 1, 2, 3, 4])

    def test_skipped_tick_advances_several_frames_at_once(self) -> None:
        # A missed monitor tick must not lose the cadence: after 1 s without
        # a redraw the next frame is four beats ahead.
        mod = load_run_pipeline()
        spinner = sys.modules["live_lines"].SPINNER_FRAMES
        with mock.patch.object(
            sys.modules["live_lines"].time,
            "monotonic",
            side_effect=[10.0, 11.0],
        ):
            live = mod.LiveLines(tty=True)
            live.set_step("study", 3)
            m = re.search(r"\[harness\] +(\S) \[study", live.block()[0])
            assert m is not None
            self.assertEqual(m.group(1), spinner[4])

    def test_frame_wraps_after_a_full_cycle(self) -> None:
        mod = load_run_pipeline()
        spinner = sys.modules["live_lines"].SPINNER_FRAMES
        heartbeat = sys.modules["live_lines"].HEARTBEAT_SECONDS
        with mock.patch.object(
            sys.modules["live_lines"].time,
            "monotonic",
            side_effect=[10.0, 10.0 + heartbeat * len(spinner)],
        ):
            live = mod.LiveLines(tty=True)
            live.set_step("study", 3)
            m = re.search(r"\[harness\] +(\S) \[study", live.block()[0])
            assert m is not None
            self.assertEqual(m.group(1), spinner[0])


class HarnessLineTest(unittest.TestCase):
    """The synthesized `[harness]` line shown until the step's first agent
    event, and its fixation at the step boundary (ADR-0012)."""

    def test_harness_line_before_any_event(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            block = live.block()
        self.assertEqual(len(block), 1)
        # No token section on the harness line; the role column is padded to
        # 18 and the spinner column is drawn on a TTY (ADR-0016).
        self.assertEqual(block[0], "[07:51:37] [harness]          \u280b [study 4/15]")

    def test_harness_line_without_step_omitted(self) -> None:
        # No known step yet (run id not discovered): nothing to draw.
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        self.assertEqual(live.block(), [])

    def test_first_event_replaces_harness_line(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        self.assertIn("[harness]", live.block()[0])
        # The first agent event of the step — any type — creates the process
        # line and replaces the harness line.
        live.add_event("planner", "", {"type": "step_start", "part": {"type": "step-start"}})
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[planner]", block[0])
        self.assertNotIn("[harness]", block[0])

    def test_parallel_forks_show_one_line_per_fork(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True)
        live.set_step("review-fan", 10)
        live.add_event("planner", "4242", _step_finish())
        live.add_event("planner", "4243", _step_finish())
        block = live.block()
        self.assertEqual(len(block), 2)
        self.assertNotIn("[harness]", block[0])
        self.assertNotIn("[harness]", block[1])

    def test_pin_all_fixes_harness_line_too(self) -> None:
        # The harness line is part of the block: pin_all keeps it as history
        # and the next step shows its own line immediately (window without a
        # line <= one monitor tick, ADR-0012). The harness is rendered
        # before the fix, like the monitor's per-tick redraw.
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        self.assertIn("[harness]", live.block()[0])
        fixed = live.pin_all()
        self.assertEqual(len(fixed), 1)
        self.assertIn("[harness]", fixed[0])
        self.assertIn("[harness]", live.block()[0])
        live.set_step("research", 4)
        self.assertIn("[research 5/15]", live.block()[0])

    def test_fixed_harness_keeps_completed_step_label(self) -> None:
        # Regression (bug fix): the engine advanced current_step_id before
        # the completion is polled, so pin_all must render the completed
        # step's harness with the step it was rendered under — never with
        # the next step's label, and never twice (once fixed, once live).
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=2, tty=True)
        live.set_step("study", 0)
        self.assertIn("[study 1/2]", live.block()[0])
        live.set_step("research", 1)
        fixed = live.pin_all("study")
        self.assertEqual(len(fixed), 1)
        self.assertIn("[harness]", fixed[0])
        self.assertIn("[study 1/2]", fixed[0])
        self.assertNotIn("research", fixed[0])
        # The next step's harness is drawn live, not fixed again.
        block = live.block()
        self.assertIn("[research 2/2]", block[0])
        self.assertNotIn("[study", block[0])

    def test_fixed_process_line_keeps_completed_step_label(self) -> None:
        # Regression (bug fix): the planner line of the completed step is
        # fixed with the completed step's label, not the already-advanced
        # next step's label.
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=2, tty=True)
        live.set_step("study", 0)
        live.add_event("planner", "", _step_finish())
        live.set_step("research", 1)
        fixed = live.pin_all("study")
        self.assertEqual(len(fixed), 1)
        self.assertIn("[planner]", fixed[0])
        self.assertIn("[study 1/2]", fixed[0])
        self.assertNotIn("research", fixed[0])
        # After the marker the next step's harness is drawn live (the fixed
        # process line is not duplicated).
        self.assertIn("[harness]", live.block()[0])
        self.assertIn("[research 2/2]", live.block()[0])

    def test_harness_belongs_to_another_step_is_left_live(self) -> None:
        # The harness line is fixed only when it belongs to the completed
        # step: a harness already rendered for the next step stays live.
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=2, tty=True)
        live.set_step("study", 0)
        live.block()
        live.set_step("research", 1)
        live.block()
        self.assertEqual(live.pin_all("study"), [])
        self.assertIn("[research 2/2]", live.block()[0])

    def test_pin_all_fixes_process_lines(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=True)
        live.set_step("study", 3)
        live.add_event("planner", "", _step_finish())
        fixed = live.pin_all()
        self.assertEqual(len(fixed), 1)
        self.assertIn("[planner]", fixed[0])
        self.assertNotIn("[harness]", fixed[0])

    def test_non_tty_step_line_once_per_step_change(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(total_steps=15, tty=False)
        with mock.patch.object(sys.modules["table_format"], "stamp", return_value="07:51:37"):
            self.assertTrue(live.set_step("study", 3))
            self.assertEqual(live.harness_step_line(), "[07:51:37] [harness]          [study 4/15]")
            # Same step: no new line; the next step gets its own.
            self.assertFalse(live.set_step("study", 3))
            self.assertTrue(live.set_step("research", 4))
            self.assertEqual(
                live.harness_step_line(), "[07:51:37] [harness]          [research 5/15]"
            )

    def test_set_step_reports_only_non_empty_changes(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=False)
        self.assertTrue(live.set_step("study", 0))
        # An empty id (run finished) is not a step start.
        self.assertFalse(live.set_step("", None))


class CursorUsageTest(unittest.TestCase):
    """The cursor usage forms accumulated by add_event (ADR-0012): a nested
    `usage` object with camelCase or snake_case keys (flat cache names or a
    nested cache dict), top-level token fields of the event itself, and the
    opencode/old-cursor `step_finish` fallback. Price is never shown on
    cursor; a malformed event is skipped whole; the process is active from
    the first any event."""

    def test_result_usage_camel_case_with_nested_cache(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event(
            "planner",
            "",
            {
                "type": "result",
                "usage": {
                    "inputTokens": 10,
                    "outputTokens": 5,
                    "reasoningTokens": 2,
                    "cache": {"read": 7, "write": 3},
                },
            },
        )
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("cache 7", block[0])
        self.assertIn("reasoning 2", block[0])
        self.assertIn("input 10", block[0])
        self.assertIn("output 5", block[0])
        self.assertNotIn("price", block[0])

    def test_result_usage_flat_cache_tokens(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event(
            "planner",
            "",
            {
                "type": "result",
                "usage": {"inputTokens": 1, "cacheReadTokens": 2, "cacheWriteTokens": 3},
            },
        )
        self.assertIn("cache 2", live.block()[0])
        self.assertIn("input 1", live.block()[0])

    def test_top_level_token_fields_of_the_event(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event("planner", "", {"type": "result", "inputTokens": 10, "outputTokens": 20})
        self.assertIn("input 10", live.block()[0])
        self.assertIn("output 20", live.block()[0])

    def test_snake_case_usage_keys(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event(
            "planner",
            "",
            {
                "type": "result",
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "reasoning_tokens": 3,
                    "cached_input_tokens": 4,
                    "cache_read_input_tokens": 5,
                },
            },
        )
        block = live.block()
        self.assertIn("cache 4", block[0])
        self.assertIn("reasoning 3", block[0])
        self.assertIn("input 1", block[0])
        self.assertIn("output 2", block[0])

    def test_cursor_accumulates_across_events(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event(
            "planner",
            "",
            {"type": "result", "usage": {"inputTokens": 10, "cacheReadTokens": 7}},
        )
        live.add_event(
            "planner",
            "",
            {"type": "result", "usage": {"input_tokens": 5, "cacheReadTokens": 3}},
        )
        block = live.block()
        self.assertIn("cache 10", block[0])
        self.assertIn("input 15", block[0])

    def test_step_finish_fallback_on_cursor_run(self) -> None:
        # Older cursor builds emit the opencode-shaped step_finish; the
        # tokens accumulate, the price stays omitted (cursor reports no
        # cost).
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event("planner", "", _step_finish(input=10, cost=0.5))
        block = live.block()
        self.assertIn("input 10", block[0])
        self.assertNotIn("price", block[0])

    def test_step_finish_fallback_ignored_after_result_usage(self) -> None:
        # Regression (bug fix): a transitional cursor build emitting both
        # shapes must not double-count — once a result-style event is seen,
        # the step_finish fallback is disabled.
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event("planner", "", {"type": "result", "usage": {"inputTokens": 100}})
        live.add_event("planner", "", _step_finish(input=100, cost=0.5))
        block = live.block()
        self.assertIn("input 100", block[0])
        self.assertNotIn("input 200", block[0])
        self.assertNotIn("price", block[0])

    def test_step_finish_fallback_before_any_result_event_still_counts(self) -> None:
        # Old cursor builds emit only step_finish events: without a
        # result-style event the fallback keeps working.
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event("planner", "", _step_finish(input=10))
        live.add_event("planner", "", {"type": "result", "usage": {"inputTokens": 5}})
        block = live.block()
        self.assertIn("input 15", block[0])

    def test_malformed_result_event_does_not_disable_step_finish_fallback(self) -> None:
        # Regression (bug fix): a malformed result-style event is skipped
        # WITHOUT flipping disable_step_finish_fallback — the step_finish
        # fallback of a later event must keep counting. One broken event
        # must not silently suppress all later token display.
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event("planner", "", {"type": "result", "usage": {"inputTokens": "abc"}})
        live.add_event("planner", "", _step_finish(input=100, cost=0.5))
        block = live.block()
        self.assertIn("input 100", block[0])
        # The malformed event still did not create a token section.
        self.assertNotIn("input 200", block[0])

    def test_unrecognized_usage_shape_does_not_disable_step_finish_fallback(self) -> None:
        # Regression (bug fix): an unrecognized-shape usage dict parses to
        # None — the flip must not happen, so the step_finish fallback of a
        # later event keeps counting.
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event("planner", "", {"type": "result", "usage": {"total": 42}})
        live.add_event("planner", "", _step_finish(input=100))
        self.assertIn("input 100", live.block()[0])

    def test_price_shown_only_on_opencode(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="opencode")
        live.add_event("planner", "", _step_finish(cost=0.5))
        self.assertIn("price $0.50", live.block()[0])

    def test_malformed_cursor_usage_skipped_whole(self) -> None:
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        malformed = [
            {"type": "result", "usage": {"inputTokens": "abc"}},
            {"type": "result", "usage": [1, 2]},
            {"type": "result", "usage": "x"},
            {"type": "result", "usage": {"inputTokens": 1, "cache": "x"}},
            {"type": "result", "inputTokens": True},
        ]
        for event in malformed:
            live.add_event("planner", "", event)
        self.assertEqual(live.block(), [])
        # A valid event afterwards still accumulates.
        live.add_event("planner", "", {"type": "result", "usage": {"inputTokens": 10}})
        self.assertIn("input 10", live.block()[0])

    def test_event_without_usage_keeps_line_tokenless(self) -> None:
        # A cursor event without any usage field: the process line shows
        # without a token section (degradation built in).
        mod = load_run_pipeline()
        live = mod.LiveLines(tty=True, backend="cursor")
        live.add_event("planner", "", {"type": "result", "part": {"type": "result"}})
        block = live.block()
        self.assertEqual(len(block), 1)
        self.assertIn("[planner]", block[0])
        self.assertNotIn("cache", block[0])
