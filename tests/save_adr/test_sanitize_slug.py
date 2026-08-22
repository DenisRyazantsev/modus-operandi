"""Unit tests for save_adr.sanitize_slug."""

import unittest

from .helpers import save_adr


class SanitizeSlugTest(unittest.TestCase):
    def test_kebab_case_from_capitalized(self) -> None:
        self.assertEqual(
            save_adr.sanitize_slug("Prod Validation Splits"),
            "prod-validation-splits",
        )

    def test_non_latin_slug_fails_with_english_message(self) -> None:
        with self.assertRaises(ValueError) as cm:
            save_adr.sanitize_slug("Продовые сплиты")
        self.assertIn("ASCII letters", str(cm.exception))

    def test_numeric_only_slug_fails(self) -> None:
        with self.assertRaises(ValueError):
            save_adr.sanitize_slug("123456")

    def test_empty_slug_fails(self) -> None:
        with self.assertRaises(ValueError):
            save_adr.sanitize_slug("")

    def test_oversized_word_is_truncated(self) -> None:
        slug = save_adr.sanitize_slug("a" * 100)
        self.assertEqual(len(slug), 60)
        self.assertEqual(slug, "a" * 60)

    def test_oversized_whole_slug_truncated_by_words(self) -> None:
        long = "word-" * 30
        slug = save_adr.sanitize_slug(long.rstrip("-"))
        self.assertLessEqual(len(slug), 60)
        self.assertFalse(slug.endswith("-"))

    def test_underscores_become_hyphens(self) -> None:
        self.assertEqual(save_adr.sanitize_slug("foo_bar_baz"), "foo-bar-baz")
