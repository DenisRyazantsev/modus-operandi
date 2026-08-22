"""modus-operandi package: the launcher and the install/bootstrap flow.

The package carries the pipeline artifacts as package data under
``data/`` (pipeline scripts, prompts, workflows, the config example and the
victory sound) and renders them into the user config base on first run
(``modus_operandi.cli.ensure_installed``). ``__version__`` is mirrored in
``pyproject.toml``; both are bumped together on release.
"""

from .paths import Paths as Paths

__version__ = "0.1.0"


class InstallError(Exception):
    """User-facing failure of the install/bootstrap flow."""

    pass
