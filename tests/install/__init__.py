"""Shared fixtures for the spec-run installer tests.

All installs go through --home <tempdir>; external commands are faked.
"""

import sys
from pathlib import Path

# The package lives in src/ (src layout); conftest.py at the repo root
# already adds it to sys.path, but keep this for direct test invocations.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
