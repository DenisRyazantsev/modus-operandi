"""Dependencies: install and uninstall specify-cli and PyYAML.

Process execution lives in proc.py, tool discovery in tool_discovery.py,
specify version parsing in versions.py, the optional yaml import in
yaml_loader.py, and environment probing (venv/network/pip) in
environment.py. Install-time presence checks live in verify.py.
"""

from __future__ import annotations

import importlib

from . import InstallError, environment, proc, tool_discovery, versions, yaml_loader
from .versions import MIN_SPECIFY_VERSION

__all__ = [
    "ensure_pyyaml",
    "ensure_specify",
    "uninstall_specify",
    "uninstall_pyyaml",
]


def ensure_pyyaml() -> None:
    if yaml_loader.yaml is not None:
        return
    if not environment.network_available():
        raise InstallError(
            "no network access and PyYAML is not installed; run: pip3 install --user pyyaml"
        )
    candidates: list[list[str]] = []
    python = tool_discovery.find_in_path("python3")
    uv = tool_discovery.find_in_path("uv")
    if environment._in_venv():
        if uv:
            candidates.append([uv, "pip", "install", "pyyaml"])
        if python and environment.pip_works(python):
            candidates.append([python, "-m", "pip", "install", "pyyaml"])
    pip3 = tool_discovery.find_in_path("pip3")
    if pip3:
        candidates.append([pip3, "install", "--user", "pyyaml"])
    if uv and not environment._in_venv():
        candidates.append([uv, "pip", "install", "--system", "pyyaml"])
    if python and not environment._in_venv() and environment.pip_works(python):
        candidates.append([python, "-m", "pip", "install", "--user", "pyyaml"])
    for cmd in candidates:
        result = proc.run(cmd, check=False)
        if result.returncode != 0:
            continue
        try:
            yaml_loader.yaml = importlib.import_module("yaml")
            return
        except ImportError:
            continue
    raise InstallError("could not install PyYAML; install it manually: pip3 install --user pyyaml")


def ensure_specify() -> None:
    version = versions.get_specify_version()
    if version and version >= MIN_SPECIFY_VERSION:
        return
    if not environment.network_available():
        raise InstallError(
            "no network access and specify-cli is not installed; run: uv tool install specify-cli"
        )
    for tool in ("uv", "pipx", "pip3"):
        path = tool_discovery.find_in_path(tool)
        if not path:
            continue
        if tool == "uv":
            result = proc.run([path, "tool", "install", "specify-cli"], check=False)
        elif tool == "pipx":
            result = proc.run([path, "install", "specify-cli"], check=False)
        else:
            result = proc.run([path, "install", "--user", "specify-cli"], check=False)
        if result.returncode != 0:
            continue
        if versions.get_specify_version():
            return
        version, binary = versions.latest_specify_version()
        if version and version >= MIN_SPECIFY_VERSION:
            print(
                f"warning: specify-cli installed at {binary} but not on PATH; "
                "add it to PATH (e.g. ~/.local/bin)"
            )
            return
    python = tool_discovery.find_in_path("python3")
    if python and environment.pip_works(python):
        result = proc.run([python, "-m", "pip", "install", "--user", "specify-cli"], check=False)
        if result.returncode == 0:
            if versions.get_specify_version():
                return
            version, binary = versions.latest_specify_version()
            if version and version >= MIN_SPECIFY_VERSION:
                print(
                    f"warning: specify-cli installed at {binary} but not on PATH; "
                    "add it to PATH (e.g. ~/.local/bin)"
                )
                return
    raise InstallError(
        "could not install specify-cli; install uv (https://docs.astral.sh/uv/) and rerun"
    )


def uninstall_specify() -> bool:
    # Teardown counterpart of ensure_specify(): only the uv-tool install is
    # removed (pip/pipx installs are left alone as they may serve other
    # projects).
    uv = tool_discovery.find_in_path("uv")
    if not uv or not versions.get_specify_version():
        return False
    result = proc.run([uv, "tool", "uninstall", "specify-cli"], check=False)
    return result.returncode == 0


def uninstall_pyyaml() -> bool:
    # Teardown counterpart of ensure_pyyaml(): tries the same install
    # locations in order — the current python's pip, then pip3, then pip3
    # --user — and succeeds on the first one that works.
    attempts: list[list[str]] = []
    python = tool_discovery.find_in_path("python3")
    if python and environment.pip_works(python):
        attempts.append([python, "-m", "pip", "uninstall", "-y", "pyyaml"])
    pip3 = tool_discovery.find_in_path("pip3")
    if pip3:
        attempts.append([pip3, "uninstall", "-y", "pyyaml"])
        attempts.append([pip3, "uninstall", "-y", "--user", "pyyaml"])
    for cmd in attempts:
        result = proc.run(cmd, check=False)
        if result.returncode == 0:
            return True
    return False
