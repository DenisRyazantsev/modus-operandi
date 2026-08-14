"""Environment probing: virtualenv detection, network reachability, pip.

These probes only serve the no-network/no-pip error branches of the install
and uninstall flows in deps.py, but they are environment questions, not
dependency management, so they live here.
"""

from __future__ import annotations

import socket
import sys

from . import proc

__all__ = ["_in_venv", "network_available", "pip_works"]


def _in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def network_available() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=5).close()
        return True
    except OSError:
        return False


def pip_works(python: str) -> bool:
    result = proc.run([python, "-m", "pip", "--version"], check=False)
    return result.returncode == 0
