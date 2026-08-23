#!/usr/bin/env python3
"""Stamp the release version into pyproject.toml and modus_operandi/__init__.py.

Called from the Build workflow (.github/workflows/build.yml) on tag pushes:
it writes the tag name into the two version declarations so `uv build`
produces a distribution matching the release. The version must not contain
a `"`, a newline or a backslash: the first would break the TOML line, the
latter two would break the python line.

The tag itself is validated against PEP 440 before stamping: a "v1.2.3" or
"release-1" tag would produce an invalid version in the built distribution,
so such tags fail the build early with an explanation instead of publishing
a broken version.
"""

import re
import sys
from pathlib import Path

_VERSION_RE = re.compile(r"^version = .*$", flags=re.MULTILINE)
_DUNDER_VERSION_RE = re.compile(r"^__version__ = .*$", flags=re.MULTILINE)

# Release tags are plain PEP 440 versions without a "v" prefix (ADR-0018):
# a "v1.2.3" or "release-1" tag would produce an invalid version in the
# built distribution, so such tags fail the build early with an explanation.
_TAG_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]*|\.dev[0-9]*|\.post[0-9]*)?$")


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
    version = sys.argv[1]
    if not _TAG_VERSION_RE.fullmatch(version):
        raise SystemExit(
            f"error: {version!r} is not a valid PEP 440 version - tags must look "
            "like 1.2.3 (no 'v' prefix)"
        )
    set_version(version, Path.cwd())


if __name__ == "__main__":
    main()
