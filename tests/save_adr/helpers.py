"""Shared fixtures for the save_adr.py tests.

save_adr.py is loaded once from the repo (it imports task_utils.py from the
same directory); the per-class result fakes live in fake_result.py and
failed_result.py.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# save_adr.py imports task_utils.py from the same directory. The directory is
# appended (not inserted at 0) so its modules never shadow the test packages
# during unittest discovery (e.g. pipeline_scripts/modus_operandi.py must not win
# over tests/modus_operandi/ when discovery imports the "modus_operandi" package).
sys.path.append(str(REPO_ROOT / "src/modus_operandi/data/pipeline_scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "save_adr_under_test", REPO_ROOT / "src/modus_operandi/data/pipeline_scripts" / "save_adr.py"
)
assert _SPEC is not None and _SPEC.loader is not None
# Registered under a distinct name so it does not shadow the tests.save_adr
# package in sys.modules (which would break the package's relative imports).
save_adr = importlib.util.module_from_spec(_SPEC)
sys.modules["save_adr_under_test"] = save_adr
_SPEC.loader.exec_module(save_adr)
