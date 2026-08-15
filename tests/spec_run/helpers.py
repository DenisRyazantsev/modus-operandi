"""Shared fixtures for the spec-run launcher tests.

The launcher derives every installed path from XDG_CONFIG_HOME/$HOME at import
time and reads the repo's install.py path from install-path.txt at edit time;
the tests point XDG_CONFIG_HOME at a temp dir and write the metadata file
there, exercising both the path derivation and the argument-mapping behavior.
"""

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = REPO_ROOT / "pipeline_scripts" / "spec_run.py"

INSTALL_PY = "/home/user/spec-kit-llm-client/install.py"


def load_spec_run(config_base: str) -> types.ModuleType:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config_base}, clear=True):
        spec = importlib.util.spec_from_file_location("spec_run_under_test", _SRC)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["spec_run_under_test"] = module
        spec.loader.exec_module(module)
    return module
