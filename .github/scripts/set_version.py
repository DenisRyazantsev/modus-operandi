#!/usr/bin/env python3
"""Stamp the release version into pyproject.toml and modus_operandi/__init__.py.

Called from the Build workflow (.github/workflows/build.yml) on tag pushes:
it writes the tag name into the two version declarations so `uv build`
produces a distribution matching the release. The version must not contain
a `"`, a newline or a backslash: the first would break the TOML line, the
latter two would break the python line.
"""

import re
import sys
from pathlib import Path

_VERSION_RE = re.compile(r"^version = .*$", flags=re.MULTILINE)
_DUNDER_VERSION_RE = re.compile(r"^__version__ = .*$", flags=re.MULTILINE)


def set_version(version: str, root: Path) -> None:
    pyproject = root / "pyproject.toml"
    text = _VERSION_RE.sub(f'version = "{version}"', pyproject.read_text(), count=1)
    pyproject.write_text(text)

    init = root / "src" / "modus_operandi" / "__init__.py"
    text = _DUNDER_VERSION_RE.sub(f'__version__ = "{version}"', init.read_text(), count=1)
    init.write_text(text)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 set_version.py <version>")
    set_version(sys.argv[1], Path.cwd())


if __name__ == "__main__":
    main()
