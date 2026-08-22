"""User prompts: interactive confirmation helpers."""

from __future__ import annotations

__all__ = ["confirm"]


def confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False
