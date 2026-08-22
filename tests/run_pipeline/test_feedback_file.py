"""Unit tests for feedback.md creation and question seeding (ADR-0012)."""

import tempfile
import unittest
from pathlib import Path

from .helpers import load_run_pipeline


class FeedbackFileTest(unittest.TestCase):
    """feedback.md is created empty when missing and never overwritten."""

    def test_creates_empty_file_with_parents(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks" / "current" / "feedback.md"
            mod.create_feedback_file(path)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_never_overwrites_existing_feedback(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            path.write_text("keep me", encoding="utf-8")
            mod.create_feedback_file(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "keep me")


class FeedbackSeedingTest(unittest.TestCase):
    """A NEW feedback.md is seeded with the numbered questions of the gate's
    open-questions section; an existing file is never touched, a missing
    document or a document without questions leaves the file empty
    (ADR-0012)."""

    def test_new_file_seeded_from_source_doc(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "study.md"
            source.write_text(
                "# Title\n\n"
                "## 5. Согласованные ответы\n\n"
                "1. not in the section\n\n"
                "## 6. Открытые вопросы\n\n"
                "Открытых вопросов не осталось.\n\n"
                "1. **Q1**\n"
                "2. Q2\n\n"
                "## 7. Next section\n\n"
                "3. also not in the section\n",
                encoding="utf-8",
            )
            path = Path(tmp) / "feedback.md"
            mod.create_feedback_file(path, source)
            self.assertEqual(path.read_text(encoding="utf-8"), "1. **Q1**\n2. Q2\n")

    def test_existing_feedback_never_overwritten_with_seed(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "study.md"
            source.write_text("## Open Questions\n\n1. Q1\n2. Q2\n", encoding="utf-8")
            path = Path(tmp) / "feedback.md"
            path.write_text("keep me", encoding="utf-8")
            mod.create_feedback_file(path, source)
            self.assertEqual(path.read_text(encoding="utf-8"), "keep me")

    def test_source_doc_without_questions_leaves_file_empty(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "adr.md"
            source.write_text("# Title\n\nNo open questions here.\n", encoding="utf-8")
            path = Path(tmp) / "feedback.md"
            mod.create_feedback_file(path, source)
            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_missing_source_doc_leaves_file_empty_not_crash(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.md"
            mod.create_feedback_file(path, Path(tmp) / "adr.md")
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "")


class QuestionsExtractionTest(unittest.TestCase):
    """The pure extraction helper (ADR-0012): only the numbered lines of the
    section whose heading contains `open questions` / `открытые вопросы`,
    up to the next heading; no section -> []."""

    def test_extracts_numbered_lines_of_the_section(self) -> None:
        mod = load_run_pipeline()
        doc = (
            "# Title\n"
            "## Some other section\n"
            "1. before the section\n"
            "## 6. Открытые вопросы\n"
            "Intro text.\n"
            "1. **Q1**\n"
            "2. Q2\n"
            "   \n"
            "## 7. Next section\n"
            "3. after the section\n"
        )
        self.assertEqual(mod.extract_numbered_questions(doc), ["1. **Q1**", "2. Q2"])

    def test_english_section_header_case_insensitive(self) -> None:
        mod = load_run_pipeline()
        doc = "# Title\n## OPEN QUESTIONS\n1. one\n2. two\n"
        self.assertEqual(mod.extract_numbered_questions(doc), ["1. one", "2. two"])

    def test_no_section_returns_empty(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.extract_numbered_questions("# Title\n1. one\n"), [])
        self.assertEqual(mod.extract_numbered_questions(""), [])

    def test_section_without_numbered_lines_returns_empty(self) -> None:
        mod = load_run_pipeline()
        doc = "# Title\n## Открытые вопросы\nNo numbered questions here.\n"
        self.assertEqual(mod.extract_numbered_questions(doc), [])

    def test_multiline_questions_captured_in_full(self) -> None:
        # A question's continuation lines (wrapped/indented, not starting
        # with a digit) belong to the question: the extracted question must
        # not be truncated to its lead line (bug fix).
        mod = load_run_pipeline()
        doc = (
            "# Title\n"
            "## 6. Открытые вопросы\n"
            "1. **Q1.** Первая строка вопроса,\n"
            "   продолжение на следующей строке.\n"
            "\n"
            "   и ещё одна строка после пустой.\n"
            "2. Q2.\n"
            "## 7. Next section\n"
            "3. not in the section\n"
        )
        self.assertEqual(
            mod.extract_numbered_questions(doc),
            [
                "1. **Q1.** Первая строка вопроса,\n"
                "продолжение на следующей строке.\n"
                "и ещё одна строка после пустой.",
                "2. Q2.",
            ],
        )

    def test_multiline_questions_seeded_into_feedback(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "study.md"
            source.write_text(
                "## Открытые вопросы\n"
                "1. Вопрос с продолжением,\n"
                "   вторая строка.\n"
                "2. Короткий вопрос.\n",
                encoding="utf-8",
            )
            path = Path(tmp) / "feedback.md"
            mod.create_feedback_file(path, source)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "1. Вопрос с продолжением,\nвторая строка.\n2. Короткий вопрос.\n",
            )


class QuestionsSourceTest(unittest.TestCase):
    """The document source of the seeding is chosen by the gate step id
    substring (ADR-0012)."""

    def test_source_by_step_id_substring(self) -> None:
        mod = load_run_pipeline()
        self.assertEqual(mod.questions_source_file("motivation-feedback-gate"), "study.md")
        self.assertEqual(
            mod.questions_source_file("motivation-loop:motivation-feedback-gate:2"),
            "study.md",
        )
        # The legacy `adr` branch of the removed adr-pipeline is gone
        # (ADR-0015): only the motivation gate seeds feedback.md.
        self.assertIsNone(mod.questions_source_file("adr-feedback-gate"))
        self.assertIsNone(mod.questions_source_file("adr-loop:adr-feedback-gate:1"))
        self.assertIsNone(mod.questions_source_file("feedback-gate"))
        self.assertIsNone(mod.questions_source_file(""))
