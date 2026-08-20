"""Optional PyYAML import, kept separate so YAML consumers do not depend on deps.

PyYAML is a declared wheel dependency of the package (pyproject.toml
`dependencies`), so at runtime ``yaml`` is always available. The lazy
importlib load survives from the pre-pip installer (which could install
PyYAML at install time instead of shipping it); it is kept because strict
mypy cannot assign ``None`` to a module-typed name, so the rebinding is the
only way to type the "not yet imported" state. Every consumer reads
``yaml_loader.yaml`` at call time.
"""

from __future__ import annotations

import importlib
from typing import Any

yaml: Any
try:
    yaml = importlib.import_module("yaml")
except ImportError:
    yaml = None

__all__ = ["yaml"]
