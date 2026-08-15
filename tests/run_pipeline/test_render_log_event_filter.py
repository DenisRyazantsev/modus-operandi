"""Unit tests for render_log_event filtering."""

import unittest

from .helpers import load_run_pipeline


class RenderLogEventFilterTest(unittest.TestCase):
    """From the agent logs only text parts with a non-empty payload are
    printed; marker events (step-start/step-finish) and empty text parts are
    dropped entirely — they carry no information and only noise up the
    output."""

    def test_text_part_with_payload_is_shown(self):
        mod = load_run_pipeline()
        role, text = mod.render_log_event(
            "executor", '{"part": {"type": "text", "text": "writing ADR"}}'
        )
        self.assertEqual((role, text), ("executor", "writing ADR"))

    def test_marker_events_and_empty_text_are_dropped(self):
        mod = load_run_pipeline()
        for line in (
            '{"type": "step-start", "part": {"type": "step-start"}}',
            '{"type": "step-finish", "part": {"type": "step-finish"}}',
            '{"type": "text", "part": {"type": "text", "text": ""}}',
            '{"type": "text", "part": {"type": "text"}}',
        ):
            self.assertEqual(mod.render_log_event("executor", line)[1], "")

    def test_non_json_line_passes_through_raw(self):
        mod = load_run_pipeline()
        role, text = mod.render_log_event("executor", "plain line")
        self.assertEqual(text, "plain line")
