#!/usr/bin/env python3
"""Text utilities for save_adr.py: slug, numbering and heading rewriting.

Kept separate from save_adr.py so the pure text rules (frontmatter slug,
filename numbering, heading normalization) are independently testable and do
not change when the release/sync orchestration changes.
"""

from __future__ import annotations

import glob
import os
import re

HEADING_RE = re.compile(r"^#\s*ADR(?:\s*-\s*\d+)?\s*:\s*(.+)$", re.M)
SLUG_ASCII_ERROR = (
    "error: slug must contain ASCII letters (English), e.g. 'slug: prod-validation-splits'"
)


def read_slug(text: str) -> str | None:
    fm = text.split("---", 2)
    if len(fm) < 3:
        return None
    m = re.search(r"^slug:\s*(\S+)", fm[1], re.M)
    return m.group(1) if m else None


def sanitize_slug(raw: str) -> str:
    if not raw:
        raise ValueError(SLUG_ASCII_ERROR)
    # Collapse everything non-latin into '-' first so a fully non-ASCII slug
    # becomes empty and trips the check below instead of producing a weird
    # filename. A slug must contain at least one English letter.
    ascii_slug = re.sub(r"[^a-z0-9-]", "-", raw.lower()).strip("-")
    if not re.search(r"[a-z]", ascii_slug):
        raise ValueError(SLUG_ASCII_ERROR)
    # Truncate by whole words to 60 chars; a single oversized word is cut
    # itself rather than making the whole slug empty.
    words = [w[:60] for w in ascii_slug.split("-") if w]
    slug = ""
    for w in words:
        if len(slug) + len(w) + (1 if slug else 0) > 60:
            break
        slug = w if not slug else slug + "-" + w
    if not slug:
        raise ValueError("error: slug is empty after sanitization")
    return slug


def find_next_number(adr_dir: str) -> int:
    nums = [
        int(m.group(1))
        for m in (
            re.search(r"ADR-(\d{4})-", f) for f in glob.glob(os.path.join(adr_dir, "ADR-*.md"))
        )
        if m
    ]
    return max(nums) + 1 if nums else 1


def rewrite_heading(text: str, num: str) -> str:
    # Replaces "# ADR: <title>" or "# ADR-0003: <title>" with the canonical
    # "# ADR-<num>: <title>", keeping the title (usually Russian) intact.
    # count=1 is a fence, not an optimization: only the TITLE heading may be
    # renumbered. Body lines that look like ADR headings (e.g. a
    # "# ADR-0002: ..." cross-reference) must survive a sync untouched, so
    # the re.M regex must not rewrite every matching line.
    return re.sub(
        HEADING_RE,
        lambda m: f"# ADR-{num}: {m.group(1).strip()}",
        text,
        count=1,
    )
