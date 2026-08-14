"""Unit tests for templates/save_adr.py (slug, numbering, heading rewrite)."""

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent

_SPEC = importlib.util.spec_from_file_location(
    "save_adr", REPO_ROOT / "templates" / "save_adr.py"
)
assert _SPEC is not None and _SPEC.loader is not None
save_adr = importlib.util.module_from_spec(_SPEC)
sys.modules["save_adr"] = save_adr
_SPEC.loader.exec_module(save_adr)


class SanitizeSlugTest(unittest.TestCase):
    def test_kebab_case_from_capitalized(self):
        self.assertEqual(
            save_adr.sanitize_slug("Prod Validation Splits"),
            "prod-validation-splits",
        )

    def test_non_latin_slug_fails_with_english_message(self):
        with self.assertRaises(ValueError) as cm:
            save_adr.sanitize_slug("Продовые сплиты")
        self.assertIn("ASCII letters", str(cm.exception))

    def test_numeric_only_slug_fails(self):
        with self.assertRaises(ValueError):
            save_adr.sanitize_slug("123456")

    def test_empty_slug_fails(self):
        with self.assertRaises(ValueError):
            save_adr.sanitize_slug("")

    def test_oversized_word_is_truncated(self):
        slug = save_adr.sanitize_slug("a" * 100)
        self.assertEqual(len(slug), 60)
        self.assertEqual(slug, "a" * 60)

    def test_oversized_whole_slug_truncated_by_words(self):
        long = "word-" * 30
        slug = save_adr.sanitize_slug(long.rstrip("-"))
        self.assertLessEqual(len(slug), 60)
        self.assertFalse(slug.endswith("-"))

    def test_underscores_become_hyphens(self):
        self.assertEqual(save_adr.sanitize_slug("foo_bar_baz"), "foo-bar-baz")


class ReadSlugTest(unittest.TestCase):
    def test_reads_slug_from_frontmatter(self):
        text = "---\nslug: prod-validation-splits\nstatus: accepted\n---\n# ADR\n"
        self.assertEqual(save_adr.read_slug(text), "prod-validation-splits")

    def test_missing_slug_returns_none(self):
        text = "---\nstatus: accepted\n---\n# ADR\n"
        self.assertIsNone(save_adr.read_slug(text))

    def test_missing_frontmatter_returns_none(self):
        self.assertIsNone(save_adr.read_slug("# ADR: test\n"))


class NumberingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adr_dir = Path(self.tmp.name)

    def test_empty_dir_starts_at_one(self):
        self.assertEqual(save_adr.find_next_number(str(self.adr_dir)), 1)

    def test_next_after_existing(self):
        for name in (
            "ADR-0001-a.md",
            "ADR-0002-b.md",
            "ADR-0003-c.md",
            "ADR-0005-d.md",
        ):
            (self.adr_dir / name).write_text("# ADR\n", encoding="utf-8")
        self.assertEqual(save_adr.find_next_number(str(self.adr_dir)), 6)


class RewriteHeadingTest(unittest.TestCase):
    def test_rewrites_plain_heading(self):
        text = "# ADR: Продовые сплиты\n\n## Context\n"
        out = save_adr.rewrite_heading(text, "0007")
        self.assertTrue(out.startswith("# ADR-0007: Продовые сплиты"))

    def test_rewrites_numbered_heading(self):
        text = "# ADR-0003: old title\nbody\n"
        out = save_adr.rewrite_heading(text, "0003")
        self.assertEqual(out.splitlines()[0], "# ADR-0003: old title")


class CmdSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)

    def adr(self, text):
        (self.task_dir / "adr.md").write_text(text, encoding="utf-8")

    def save(self):
        save_adr.cmd_save(
            argparse.Namespace(
                state_dir=str(self.root / ".workflow"),
                task_id="t1",
                adr_dir=str(self.root / "architecture"),
                run_agent="/nonexistent/run-agent.sh",
            )
        )

    def test_save_with_slug_creates_adr(self):
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты\n")
        self.save()
        saved = self.root / "architecture" / "ADR-0001-prod-validation-splits.md"
        self.assertTrue(saved.exists())
        self.assertIn("# ADR-0001: Сплиты", saved.read_text(encoding="utf-8"))
        saved_txt = (self.task_dir / "adr-saved.txt").read_text(encoding="utf-8")
        self.assertEqual(saved_txt, str(saved))

    def test_save_is_idempotent_by_slug(self):
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты\n")
        self.save()
        self.save()
        files = list((self.root / "architecture").glob("ADR-*.md"))
        self.assertEqual(len(files), 1)

    def test_missing_slug_asks_planner(self):
        self.adr("---\nstatus: accepted\n---\n# ADR: Сплиты\n")

        def fake_run(cmd, shell=False, check=True):
            assert check is True
            assert "planner" in cmd
            adr = self.task_dir / "adr.md"
            text = adr.read_text(encoding="utf-8")
            adr.write_text(
                text.replace("status: accepted", "slug: prod-validation-splits\nstatus: accepted"),
                encoding="utf-8",
            )

        with mock.patch("subprocess.run", side_effect=fake_run):
            self.save()
        saved = self.root / "architecture" / "ADR-0001-prod-validation-splits.md"
        self.assertTrue(saved.exists())

    def test_planner_refusal_fails(self):
        self.adr("---\nstatus: accepted\n---\n# ADR: Сплиты\n")
        with mock.patch("subprocess.run"), self.assertRaises(SystemExit) as cm:
            self.save()
        self.assertIn("slug", str(cm.exception))


class CmdSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)
        self.arch = self.root / "architecture"
        self.arch.mkdir()

    def test_sync_rewrites_heading_from_filename(self):
        target = self.arch / "ADR-0007-prod-validation-splits.md"
        target.write_text("# ADR-0007: old\n", encoding="utf-8")
        (self.task_dir / "adr-saved.txt").write_text(str(target), encoding="utf-8")
        (self.task_dir / "adr.md").write_text(
            "# ADR: updated title\n## Amendments\n- x\n", encoding="utf-8"
        )
        save_adr.cmd_sync(
            argparse.Namespace(
                state_dir=str(self.root / ".workflow"), task_id="t1"
            )
        )
        out = target.read_text(encoding="utf-8")
        self.assertTrue(out.startswith("# ADR-0007: updated title"))
        self.assertIn("## Amendments", out)

    def test_sync_missing_saved_file_fails(self):
        with self.assertRaises(SystemExit):
            save_adr.cmd_sync(
                argparse.Namespace(
                    state_dir=str(self.root / ".workflow"), task_id="t1"
                )
            )


if __name__ == "__main__":
    unittest.main()
