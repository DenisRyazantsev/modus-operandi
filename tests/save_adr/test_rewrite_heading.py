"""Unit tests for save_adr.rewrite_heading."""

import unittest

from .helpers import save_adr


class RewriteHeadingTest(unittest.TestCase):
    def test_rewrites_plain_heading(self):
        text = "# ADR: Продовые сплиты\n\n## Context\n"
        out = save_adr.rewrite_heading(text, "0007")
        self.assertTrue(out.startswith("# ADR-0007: Продовые сплиты"))

    def test_rewrites_numbered_heading(self):
        text = "# ADR-0003: old title\nbody\n"
        out = save_adr.rewrite_heading(text, "0003")
        self.assertEqual(out.splitlines()[0], "# ADR-0003: old title")
