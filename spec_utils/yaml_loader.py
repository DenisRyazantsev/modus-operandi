"""Optional PyYAML import, kept separate so YAML consumers do not depend on deps.

PyYAML is optional at import time (deps.ensure_pyyaml() can install it later).
We load it through importlib so the module-level name can be annotated as Any
and later rebound to the real module — a plain `try: import yaml / except
ImportError: yaml = None` is a type error under strict mypy (a module type is
not assignable to None), and rebinding works here because every consumer reads
yaml_loader.yaml at call time.
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
