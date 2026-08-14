"""Environment bootstrap: python/uv/pip/specify/pyyaml discovery and install."""

from __future__ import annotations

import importlib
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import InstallError

# PyYAML is optional at import time (the installer can install it later via
# ensure_pyyaml()).  We load it through importlib so the module-level name can
# be annotated as Any and later rebound to the real module — a plain
# `try: import yaml / except ImportError: yaml = None` is a type error under
# strict mypy (a module type is not assignable to None), and rebinding works
# here because every consumer reads deps.yaml at call time.
yaml: Any
try:
    yaml = importlib.import_module("yaml")
except ImportError:
    yaml = None

__all__ = [
    "MIN_SPECIFY_VERSION",
    "yaml",
    "find_in_path",
    "run",
    "network_available",
    "parse_specify_version",
    "_specify_candidates",
    "get_specify_version",
    "latest_specify_version",
    "_in_venv",
    "pip_works",
    "check_prerequisites",
    "ensure_pyyaml",
    "ensure_specify",
]

MIN_SPECIFY_VERSION = (0, 16)


def find_in_path(name: str) -> str | None:
    return shutil.which(name)


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


def network_available() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=5).close()
        return True
    except OSError:
        return False


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
    path = find_in_path("specify")
    if not path:
        return None
    result = run([path, "--version"], check=False)
    if result.returncode != 0:
        return None
    return parse_specify_version(result.stdout)


def latest_specify_version() -> tuple[tuple[int, int] | None, str | None]:
    # Returns (version, path) of the newest specify-cli found anywhere we could
    # have installed it — on PATH or in the explicit ~/.local locations. Used by
    # ensure_specify() to detect an install that succeeded but is invisible to
    # shutil.which() (binary not on PATH).
    paths = [p for p in _specify_candidates() + [find_in_path("specify")] if p]
    for path in paths:
        result = run([path, "--version"], check=False)
        if result.returncode != 0:
            continue
        version = parse_specify_version(result.stdout)
        if version:
            return version, path
    return None, None


def _in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def pip_works(python: str) -> bool:
    result = run([python, "-m", "pip", "--version"], check=False)
    return result.returncode == 0


def check_prerequisites() -> None:
    if not find_in_path("python3"):
        raise InstallError("python3 not found in PATH")
    if not find_in_path("opencode"):
        raise InstallError(
            "opencode not found in PATH - install it first (https://opencode.ai/docs)"
        )


def ensure_pyyaml() -> None:
    global yaml
    if yaml is not None:
        return
    if not network_available():
        raise InstallError(
            "no network access and PyYAML is not installed; "
            "run: pip3 install --user pyyaml"
        )
    candidates: list[list[str]] = []
    python = find_in_path("python3")
    uv = find_in_path("uv")
    if _in_venv():
        if uv:
            candidates.append([uv, "pip", "install", "pyyaml"])
        if python and pip_works(python):
            candidates.append([python, "-m", "pip", "install", "pyyaml"])
    pip3 = find_in_path("pip3")
    if pip3:
        candidates.append([pip3, "install", "--user", "pyyaml"])
    if uv and not _in_venv():
        candidates.append([uv, "pip", "install", "--system", "pyyaml"])
    if python and not _in_venv() and pip_works(python):
        candidates.append([python, "-m", "pip", "install", "--user", "pyyaml"])
    for cmd in candidates:
        result = run(cmd, check=False)
        if result.returncode != 0:
            continue
        try:
            yaml = importlib.import_module("yaml")
            return
        except ImportError:
            continue
    raise InstallError(
        "could not install PyYAML; install it manually: pip3 install --user pyyaml"
    )


def ensure_specify() -> None:
    version = get_specify_version()
    if version and version >= MIN_SPECIFY_VERSION:
        return
    if not network_available():
        raise InstallError(
            "no network access and specify-cli is not installed; "
            "run: uv tool install specify-cli"
        )
    for tool in ("uv", "pipx", "pip3"):
        path = find_in_path(tool)
        if not path:
            continue
        if tool == "uv":
            result = run([path, "tool", "install", "specify-cli"], check=False)
        elif tool == "pipx":
            result = run([path, "install", "specify-cli"], check=False)
        else:
            result = run([path, "install", "--user", "specify-cli"], check=False)
        if result.returncode != 0:
            continue
        if get_specify_version():
            return
        version, binary = latest_specify_version()
        if version and version >= MIN_SPECIFY_VERSION:
            print(
                f"warning: specify-cli installed at {binary} but not on PATH; "
                "add it to PATH (e.g. ~/.local/bin)"
            )
            return
    python = find_in_path("python3")
    if python and pip_works(python):
        result = run(
            [python, "-m", "pip", "install", "--user", "specify-cli"], check=False
        )
        if result.returncode == 0:
            if get_specify_version():
                return
            version, binary = latest_specify_version()
            if version and version >= MIN_SPECIFY_VERSION:
                print(
                    f"warning: specify-cli installed at {binary} but not on PATH; "
                    "add it to PATH (e.g. ~/.local/bin)"
                )
                return
    raise InstallError(
        "could not install specify-cli; install uv "
        "(https://docs.astral.sh/uv/) and rerun"
    )
