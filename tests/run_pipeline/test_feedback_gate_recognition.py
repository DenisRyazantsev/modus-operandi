"""Unit tests for the feedback-gate step id recognition."""

import unittest

from .helpers import load_run_pipeline


class FeedbackGateRecognitionTest(unittest.TestCase):
    """The revise feedback gate is recognized by the "feedback-gate"
    substring of the step id (plain and loop-iteration forms)."""

    def test_recognizes_feedback_gate_ids(self) -> None:
        mod = load_run_pipeline()
        self.assertTrue(mod.is_feedback_gate("adr-feedback-gate"))
        self.assertTrue(mod.is_feedback_gate("adr-loop:adr-feedback-gate:1"))
        self.assertTrue(mod.is_feedback_gate("adr-loop:adr-feedback-gate:2"))

    def test_rejects_other_ids(self) -> None:
        mod = load_run_pipeline()
        self.assertFalse(mod.is_feedback_gate("adr-gate"))
        self.assertFalse(mod.is_feedback_gate("adr-approval-gate"))
        self.assertFalse(mod.is_feedback_gate("adr-loop:adr-gate:1"))
        self.assertFalse(mod.is_feedback_gate(""))
        self.assertFalse(mod.is_feedback_gate(None))
