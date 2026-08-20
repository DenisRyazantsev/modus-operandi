"""Tool discovery: locate executables on PATH."""

from __future__ import annotations

import shutil

__all__ = ["find_in_path"]


def find_in_path(name: str) -> str | None:
    return shutil.which(name)
