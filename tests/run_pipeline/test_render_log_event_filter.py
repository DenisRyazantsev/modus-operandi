"""Unit tests for render_log_event filtering."""

import unittest

from .helpers import load_run_pipeline


class RenderLogEventFilterTest(unittest.TestCase):
    """Since ADR-0011 nothing is printed from the agent logs: `text` and
    `reasoning` events and raw non-JSON lines are all suppressed (the live
    status lines replace the old log echo). The function keeps its (role,
    text) contract, always returning an empty text."""

    def test_text_events_are_suppressed(self) -> None:
        mod = load_run_pipeline()
        role, text = mod.render_log_event(
            "executor", '{"part": {"type": "text", "text": "writing ADR"}}'
        )
        self.assertEqual((role, text), ("executor", ""))

    def test_all_event_types_are_suppressed(self) -> None:
        mod = load_run_pipeline()
        for line in (
            '{"type": "step-start", "part": {"type": "step-start"}}',
            '{"type": "step-finish", "part": {"type": "step-finish"}}',
            '{"type": "text", "part": {"type": "text", "text": "x"}}',
            '{"type": "reasoning", "part": {"type": "reasoning", "text": "y"}}',
            '{"part": {"type": "text", "text": ""}}',
            '{"part": {"type": "text"}}',
        ):
            self.assertEqual(mod.render_log_event("executor", line)[1], "")

    def test_non_json_line_is_suppressed(self) -> None:
        mod = load_run_pipeline()
        role, text = mod.render_log_event("executor", "plain line")
        self.assertEqual((role, text), ("executor", ""))
