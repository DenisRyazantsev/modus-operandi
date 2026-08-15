"""Unit tests for save_adr.read_slug."""

import unittest

from .helpers import save_adr


class ReadSlugTest(unittest.TestCase):
    def test_reads_slug_from_frontmatter(self):
        text = "---\nslug: prod-validation-splits\nstatus: accepted\n---\n# ADR\n"
        self.assertEqual(save_adr.read_slug(text), "prod-validation-splits")

    def test_missing_slug_returns_none(self):
        text = "---\nstatus: accepted\n---\n# ADR\n"
        self.assertIsNone(save_adr.read_slug(text))

    def test_missing_frontmatter_returns_none(self):
        self.assertIsNone(save_adr.read_slug("# ADR: test\n"))
