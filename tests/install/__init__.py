"""Shared fixtures for the spec-kit-llm-client installer tests.

All installs go through --home <tempdir>; external commands are faked.
"""

import sys
from pathlib import Path

# spec_utils lives at the repo root, one level above the tests package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
