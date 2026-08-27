---
slug: document-block-display
status: accepted
date: 2026-08-26
---

# ADR-0021: Long-form documents (the executor summary) display as free-form blocks, not as table rows

## Context

Since ADR-0019, both pipelines end with the executor's final summary — a multi-paragraph markdown document — which the workflow displays through a step whose captured stdout the wrapper re-emits as `[harness]` rows of the aligned log table (ADR-0016). That table was designed for short one-line events; a document forced through it gets every line prefixed by the timestamp, the role column and the padded empty step column (about sixty characters), so the text starts far from the right of the left edge and wraps at arbitrary points — an unreadable wall of text. This defeats the very purpose of the summary (ADR-0019: the user-facing answer to "what was done", usable as a commit-message basis). The wrapper already has a precedent for non-table output: the run statistics block and the latency table keep their own form (ADR-0016).

## Decision

Long-form documents emitted by workflow steps — the final executor summary today, any document shown this way in the future — are displayed as a free-form block, not as per-line table rows:

- The block is announced by a single `[harness]` table row (timestamp, role, label) and the document text then prints verbatim from the left margin, without per-line prefixes. Raw markdown is preserved; lines are printed as-is and the terminal performs the word wrapping — no wrapper-side reflow.
- The wrapper recognizes the block through an opt-in marker protocol in the step's captured stdout: the displaying script wraps the document in begin/end marker lines; the wrapper renders the content between them as a block and strips the markers. The protocol is generic — any step can opt into document display, and the wrapper never hardcodes workflow step ids.
- The behavior degrades gracefully: when the markers are absent or torn (unclosed), the output falls back to the current per-line table behavior; display never raises in the live-status path.
- The block renders identically on a TTY and on a non-TTY (no spinner, no line truncation in redirected output — the no-loss rule of ADR-0016).

This is the established framing pattern (marker-delimited blocks in a text stream — GitHub Actions groups, heredocs, PGP/PEM armor), keeps the display inside the workflow, and exempts document lines from the table exactly like the statistics block is exempt.

## Alternatives

- **The wrapper displays the summary itself at run end** (reads the file like the statistics block). Rejected: changes the structure of both pipelines and their structural tests, loses the display under a direct engine run without the wrapper, duplicates file reading and control-character stripping.
- **Wrapper-side reflow to a fixed width.** Rejected: explicit refilling breaks terminal copy/paste and user expectations (soft wrap is the norm), double-wraps (we wrap, the terminal wraps again), and conflicts with the no-width-based-formatting rule in non-TTY.
- **Table prefix on the first line, indented continuation lines** (the logging-formatter pattern). Rejected: the first line still starts far from the left edge — the very complaint being fixed.
- **Markdown rendering with color (rich/glow-style).** Rejected: new dependencies (rich was already dropped), raw markdown is the industry default for LLM output, and styled output would clash with the existing control-character stripping.
- **Special-casing a known step id in the wrapper.** Rejected: couples the wrapper to workflow internals; the generic marker protocol costs the same.
- **Pager or editor for the summary.** Rejected: the summary is short and must stay in the run's log stream; pagers conflict with the streaming live output and the gates.

## Consequences

- Positive: the final summary becomes readable — text starts at the left margin, wraps at word boundaries, raw markdown preserved; ADR-0019's goal is met.
- Positive: the aligned log table stays intact — the announcement row keeps one-actor attribution (ADR-0013/0016), and the document lines are exempt like the statistics block.
- Positive: the generic protocol lets any future step show a document without wrapper changes.
- Positive: malformed output degrades to the previous behavior; the run and the live status are never affected.
- Negative: a new public convention on step stdout — marker lines are visible in the captured step output (stripped by the wrapper) and must be documented.
- Negative: a marker string could theoretically collide with document content; mitigated by whole-line exact matching (the same accepted risk as PGP armor).
- Negative: raw markdown is shown as-is, without rendering — accepted, consistent with the industry default for LLM output.

## Acceptance Criteria

- The final executor summary in both pipelines displays as a block: one `[harness]` announcement row, then the document text starting at the left margin, without per-line timestamp/role/step prefixes.
- Long lines wrap at the terminal's word boundaries; the content is printed as-is (raw markdown, no ANSI, no wrapper-side reflow or truncation).
- The block is opt-in via the marker protocol: steps that do not emit markers keep the current per-line `[harness]` row behavior.
- A missing or torn marker pair degrades to the per-line behavior without failing the run or disturbing the live status.
- The block renders the same on a TTY and on a non-TTY; redirected output keeps the full text.
