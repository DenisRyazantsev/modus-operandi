"""Feedback-gate domain: gate recognition and the feedback.md seeding.

One responsibility: own the feedback-gate contract between the installed
workflows and the wrapper — the marker substring shared with the shipped
gate step id, the gate-recognition predicate, the questions-source mapping
(which document's open-questions section seeds feedback.md) and the
numbered-question extraction. The wrapper (run_pipeline.py) and the
feedback editor (feedback_editor.py) consume these; the installed
task-pipeline.yml is the cross-file counterpart.
"""

from __future__ import annotations

import re

# Substring that identifies the feedback gate in a step id. The only
# feedback gate the installed workflows ship is the task pipeline's
# `motivation-feedback-gate` (task-pipeline.yml); the marker matches it
# by substring, so current_step_id from state.json is the wrapper's only
# observation point for "which gate opened". This is a deliberate
# cross-file coupling — renaming the step silently disables the editor
# path and the gate signals like a normal gate again.
FEEDBACK_GATE_MARKER = "feedback-gate"


def is_feedback_gate(step_id: str | None) -> bool:
    """True when the step id identifies a feedback gate.

    Matches any shipped gate id containing "feedback-gate" (currently only
    `motivation-feedback-gate` in task-pipeline.yml) by substring. Pure
    predicate, so the gate recognition is unit-testable without a running
    workflow.
    """
    return step_id is not None and FEEDBACK_GATE_MARKER in step_id


def questions_source_file(step_id: str) -> str | None:
    """The document whose open-questions section seeds feedback.md.

    Selected by the gate step id substring (ADR-0012): a gate id containing
    `motivation` seeds from study.md (the motivation clarify gate — the only
    feedback gate the installed workflows ship); anything else — no seeding,
    the file stays empty. Pure function for unit tests.
    """
    if "motivation" in step_id:
        return "study.md"
    return None


def extract_numbered_questions(doc: str) -> list[str]:
    r"""The numbered questions of the document's open-questions section.

    The section is the one whose heading (a line starting with `#`) contains
    `open questions` or `открытые вопросы` (case-insensitive); its numbered
    lines (`^\d+.`) up to the next heading are the questions. A question
    keeps its continuation lines — wrapped or indented, not starting with a
    digit — until the next numbered line or the next heading (blank lines
    are skipped), so a multi-line question is captured in full, not
    truncated to its lead (bug fix). Lines are returned stripped of
    surrounding whitespace. No such section — or none of its lines are
    numbered — yields []. Pure helper of the feedback.md seeding
    (ADR-0012), unit-tested without a running workflow.
    """
    questions: list[str] = []
    current: list[str] | None = None
    in_section = False
    for line in doc.splitlines():
        if line.startswith("#"):
            if in_section:
                break
            if re.search(r"open questions|открытые вопросы", line, re.IGNORECASE):
                in_section = True
            continue
        if not in_section:
            continue
        if re.match(r"^\d+\.", line):
            if current is not None:
                questions.append("\n".join(current))
            current = [line.strip()]
        elif current is not None:
            stripped = line.strip()
            if stripped:
                current.append(stripped)
    if current is not None:
        questions.append("\n".join(current))
    return questions
