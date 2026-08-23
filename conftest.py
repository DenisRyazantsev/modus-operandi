"""Make the src-layout package importable for the tests.

The run-pipeline wrapper (run-pipeline.py) exports its MO_* runtime
variables into child processes, so a suite run under the wrapper's own
environment would see e.g. MO_PROMPTS_DIR already set. The run-pipeline
tests assume a clean environment (they assert the derived defaults), so
the wrapper's exports are scrubbed before every test; a test that needs
one sets it explicitly through the env() sandbox.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# The wrapper's runtime exports. An ambient value would override the
# derived defaults the tests assert on. Consumers: config_invocation.py
# reads MO_CONFIG and MO_PROMPTS_DIR to derive values; run-agent.sh and
# name-task.sh read the rest (MO_SCRIPTS_DIR is consumed by the workflow
# steps' ${MO_SCRIPTS_DIR:-...} path expansion, not by run-agent.sh).
_MO_ENV_VARS = (
    "MO_CONFIG",
    "MO_SCRIPTS_DIR",
    "MO_PROMPTS_DIR",
    "MO_STATE_DIR",
    "MO_BACKEND",
    "MO_ATTACH_FLAG",
    "MO_PLANNER_MODEL",
    "MO_EXECUTOR_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_mo_env() -> None:
    """Remove the wrapper's MO_* exports for the duration of each test."""
    for key in _MO_ENV_VARS:
        os.environ.pop(key, None)
