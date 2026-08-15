"""Unit tests for the gate-menu opener line recognition."""

import unittest

from .helpers import load_run_pipeline


class GateMenuRecognitionTest(unittest.TestCase):
    """The wrapper pauses its own live output only while a human-gate menu
    window is on screen; recognizing the window's first line is a pure
    string predicate."""

    def test_recognizes_menu_opener_line(self):
        mod = load_run_pipeline()
        self.assertTrue(mod.is_gate_menu_opener("┌─ Gate ───────────"))
        self.assertTrue(mod.is_gate_menu_opener("  ┌─ Gate ···"))  # leading spaces
        self.assertTrue(mod.is_gate_menu_opener("┌─ Gate"))

    def test_rejects_other_lines(self):
        mod = load_run_pipeline()
        self.assertFalse(mod.is_gate_menu_opener(""))
        self.assertFalse(mod.is_gate_menu_opener("writing the ADR..."))
        self.assertFalse(mod.is_gate_menu_opener("│ 1. approve"))  # menu body line
        self.assertFalse(mod.is_gate_menu_opener("┌─ Not a gate"))
