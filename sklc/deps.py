"""Environment bootstrap: python/uv/pip/specify/pyyaml discovery and install."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from . import InstallError

try:
    import yaml
except ImportError:
    yaml = None

MIN_SPECIFY_VERSION = (0, 16)


def find_in_path(name):
    return shutil.which(name)


def run(cmd, cwd=None, env=None, check=True):
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise InstallError(
            "command failed with exit code %d: %s\n%s"
            % (result.returncode, " ".join(cmd), result.stderr.strip())
        )
    return result


def network_available():
    try:
        socket.create_connection(("pypi.org", 443), timeout=5).close()
        return True
    except OSError:
        return False


def parse_specify_version(text):
    m = re.search(r"(\d+)\.(\d+)", text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _specify_candidates():
    exe = "specify.exe" if os.name == "nt" else "specify"
    candidates = []
    for base in (
        Path.home() / ".local" / "bin",
        Path.home() / ".local" / "share" / "uv" / "tools" / "specify-cli" / "bin",
    ):
        candidate = base / exe
        if candidate.exists():
            candidates.append(str(candidate))
    return candidates


def get_specify_version():
    path = find_in_path("specify")
    if not path:
        return None
    result = run([path, "--version"], check=False)
    if result.returncode != 0:
        return None
    return parse_specify_version(result.stdout)


def latest_specify_version():
    for path in _specify_candidates() + [find_in_path("specify")]:
        if not path:
            continue
        result = run([path, "--version"], check=False)
        if result.returncode != 0:
            continue
        version = parse_specify_version(result.stdout)
        if version:
            return version, path
    return None, None


def _in_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def check_prerequisites():
    if not find_in_path("python3"):
        raise InstallError("python3 not found in PATH")
    if not find_in_path("opencode"):
        raise InstallError(
            "opencode not found in PATH - install it first (https://opencode.ai/docs)"
        )


def _pip_works(python):
    result = run([python, "-m", "pip", "--version"], check=False)
    return result.returncode == 0


def ensure_pyyaml():
    global yaml
    if yaml is not None:
        return
    if not network_available():
        raise InstallError(
            "no network access and PyYAML is not installed; "
            "run: pip3 install --user pyyaml"
        )
    candidates = []
    python = find_in_path("python3")
    uv = find_in_path("uv")
    if _in_venv():
        if uv:
            candidates.append([uv, "pip", "install", "pyyaml"])
        if python and _pip_works(python):
            candidates.append([python, "-m", "pip", "install", "pyyaml"])
    pip3 = find_in_path("pip3")
    if pip3:
        candidates.append([pip3, "install", "--user", "pyyaml"])
    if uv and not _in_venv():
        candidates.append([uv, "pip", "install", "--system", "pyyaml"])
    if python and not _in_venv() and _pip_works(python):
        candidates.append([python, "-m", "pip", "install", "--user", "pyyaml"])
    for cmd in candidates:
        result = run(cmd, check=False)
        if result.returncode != 0:
            continue
        try:
            import importlib

            yaml = importlib.import_module("yaml")
            return
        except ImportError:
            continue
    raise InstallError(
        "could not install PyYAML; install it manually: pip3 install --user pyyaml"
    )


def ensure_specify():
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
                "warning: specify-cli installed at %s but not on PATH; "
                "add it to PATH (e.g. ~/.local/bin)" % binary
            )
            return
    python = find_in_path("python3")
    if python and _pip_works(python):
        result = run([python, "-m", "pip", "install", "--user", "specify-cli"], check=False)
        if result.returncode == 0:
            if get_specify_version():
                return
            version, binary = latest_specify_version()
            if version and version >= MIN_SPECIFY_VERSION:
                print(
                    "warning: specify-cli installed at %s but not on PATH; "
                    "add it to PATH (e.g. ~/.local/bin)" % binary
                )
                return
    raise InstallError(
        "could not install specify-cli; install uv "
        "(https://docs.astral.sh/uv/) and rerun"
    )
