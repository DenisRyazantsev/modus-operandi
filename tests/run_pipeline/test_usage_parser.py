"""Unit tests for the agent-log usage parser (usage_parser.py, ADR-0012)."""

import sys
import unittest
from typing import Any

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


class UsageParserTest(unittest.TestCase):
    """The parser's precedence contract (bug fix): the shapes of one event
    are precedence-ordered, not cumulative, and `disable_step_finish_fallback`
    disables the step_finish fallback once the task's logs have shown the
    modern shape — a transitional build emitting both shapes must not
    double-count."""

    def _parser(self) -> Any:
        load_run_pipeline()
        return sys.modules["usage_parser"]

    def test_result_usage_wins_over_flat_fields_of_the_same_event(self) -> None:
        # A nested usage object, when present, is taken as the whole usage:
        # the flat branches must not fire for the same event.
        parser = self._parser()
        usage = parser.event_usage(
            {"type": "result", "usage": {"inputTokens": 5}, "inputTokens": 100}
        )
        self.assertEqual(usage["input"], 5)

    def test_nested_cache_overrides_flat_cache_names_per_field(self) -> None:
        # Precedence, not accumulation: when one usage dict carries BOTH the
        # flat cache names and the nested cache dict, the nested values
        # override the flat ones per field (cache_read/cache_write) — a
        # "fix" summing the two would double-count the same tokens
        # (documented contract in _parse_usage).
        parser = self._parser()
        usage = parser.event_usage(
            {
                "type": "result",
                "usage": {
                    "cacheReadTokens": 10,
                    "cacheWriteTokens": 20,
                    "cache": {"read": 3, "write": 4},
                },
            }
        )
        self.assertEqual(usage["cache_read"], 3)
        self.assertEqual(usage["cache_write"], 4)
        # A nested dict without the flat names keeps the nested values.
        self.assertEqual(
            parser.event_usage({"type": "result", "usage": {"cache": {"read": 7}}})["cache_read"],
            7,
        )

    def test_no_usage_key_consults_flat_and_step_finish_branches(self) -> None:
        parser = self._parser()
        self.assertEqual(parser.event_usage({"type": "result", "inputTokens": 100})["input"], 100)
        self.assertEqual(parser.event_usage(_step_finish(input=100))["input"], 100)

    def test_disable_step_finish_fallback_flag(self) -> None:
        parser = self._parser()
        event = _step_finish(input=100, cost=0.5)
        self.assertEqual(parser.event_usage(event)["input"], 100)
        # The result-style branches are unaffected by the flag.
        self.assertEqual(
            parser.event_usage({"type": "result", "usage": {"inputTokens": 5}}, True)["input"],
            5,
        )
        self.assertIsNone(
            parser.event_usage(event, disable_step_finish_fallback=True)
        )

    def test_is_result_style_detects_the_modern_shapes(self) -> None:
        parser = self._parser()
        self.assertTrue(parser.is_result_style({"type": "result", "usage": {"inputTokens": 1}}))
        self.assertTrue(parser.is_result_style({"type": "result", "inputTokens": 1}))
        # A malformed usage key still marks the event as result-style.
        self.assertTrue(parser.is_result_style({"type": "result", "usage": "x"}))
        self.assertFalse(parser.is_result_style(_step_finish()))
        self.assertFalse(parser.is_result_style({"type": "text", "part": {"type": "text"}}))

    def test_unrecognized_usage_shape_parses_to_none(self) -> None:
        # An unrecognized-shape usage dict yields None (no recognized keys),
        # not an exception and not a partial dict — so the callers skip the
        # event without flipping disable_step_finish_fallback (bug fix).
        parser = self._parser()
        self.assertIsNone(parser.event_usage({"type": "result", "usage": {"total": 42}}))
