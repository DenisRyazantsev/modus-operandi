"""Process execution: subprocess runs with error mapping."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import InstallError

__all__ = ["run"]


def run(
    cmd: list[str],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise InstallError(
            f"command failed with exit code {result.returncode}: "
            f"{' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result
