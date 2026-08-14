"""specify-cli version parsing and discovery."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import proc, tool_discovery

__all__ = [
    "MIN_SPECIFY_VERSION",
    "parse_specify_version",
    "_specify_candidates",
    "get_specify_version",
    "latest_specify_version",
]

MIN_SPECIFY_VERSION = (0, 16)


def parse_specify_version(text: str | None) -> tuple[int, int] | None:
    m = re.search(r"(\d+)\.(\d+)", text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _specify_candidates() -> list[str]:
    # uv tool / pipx / pip --user install binaries into ~/.local/bin (uv keeps
    # the real copy under ~/.local/share/uv/tools/.../bin). Those paths are NOT
    # always on PATH, so after an install we must probe them explicitly —
    # otherwise a successful install would look like a failure.
    exe = "specify.exe" if os.name == "nt" else "specify"
    candidates: list[str] = []
    for base in (
        Path.home() / ".local" / "bin",
        Path.home() / ".local" / "share" / "uv" / "tools" / "specify-cli" / "bin",
    ):
        candidate = base / exe
        if candidate.exists():
            candidates.append(str(candidate))
    return candidates


def get_specify_version() -> tuple[int, int] | None:
    path = tool_discovery.find_in_path("specify")
    if not path:
        return None
    result = proc.run([path, "--version"], check=False)
    if result.returncode != 0:
        return None
    return parse_specify_version(result.stdout)


def latest_specify_version() -> tuple[tuple[int, int] | None, str | None]:
    # Returns (version, path) of the newest specify-cli found anywhere we could
    # have installed it — on PATH or in the explicit ~/.local locations. Used by
    # ensure_specify() to detect an install that succeeded but is invisible to
    # shutil.which() (binary not on PATH). All candidates are probed and the
    # highest version wins: probe order (~/.local/bin, uv tools, PATH) does not
    # imply version order, so the first parseable candidate is not necessarily
    # the newest.
    paths = [p for p in _specify_candidates() + [tool_discovery.find_in_path("specify")] if p]
    best: tuple[tuple[int, int] | None, str | None] = (None, None)
    for path in paths:
        result = proc.run([path, "--version"], check=False)
        if result.returncode != 0:
            continue
        version = parse_specify_version(result.stdout)
        if version and (best[0] is None or version > best[0]):
            best = (version, path)
    return best
