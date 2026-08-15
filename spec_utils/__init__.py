"""spec-kit-llm-client installer package."""

from pathlib import Path

from .paths import Paths as Paths

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "pipeline_scripts"
WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"
CONFIG_EXAMPLE = REPO_ROOT / "config.example.yml"


class InstallError(Exception):
    pass
