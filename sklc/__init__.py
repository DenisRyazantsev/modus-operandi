"""spec-kit-llm-client installer package."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
CONFIG_EXAMPLE = REPO_ROOT / "config.example.yml"

Paths = dict[str, Path]


class InstallError(Exception):
    pass
