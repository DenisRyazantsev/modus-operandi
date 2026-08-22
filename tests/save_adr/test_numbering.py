"""Unit tests for save_adr.find_next_number."""

import tempfile
import unittest
from pathlib import Path

from .helpers import save_adr


class NumberingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adr_dir = Path(self.tmp.name)

    def test_empty_dir_starts_at_one(self) -> None:
        self.assertEqual(save_adr.find_next_number(str(self.adr_dir)), 1)

    def test_next_after_existing(self) -> None:
        for name in (
            "ADR-0001-a.md",
            "ADR-0002-b.md",
            "ADR-0003-c.md",
            "ADR-0005-d.md",
        ):
            (self.adr_dir / name).write_text("# ADR\n", encoding="utf-8")
        self.assertEqual(save_adr.find_next_number(str(self.adr_dir)), 6)
