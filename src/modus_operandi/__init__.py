"""modus-operandi package: the launcher and the install/bootstrap flow.

The package carries the pipeline artifacts as package data under
``data/`` (pipeline scripts, prompts, workflows, the config example and the
victory sound) and renders them into the user config base on first run
(``modus_operandi.cli.ensure_installed``). ``__version__`` is mirrored in
``pyproject.toml``; both are bumped together on release. The checkout
carries the 0.0.0.dev0 placeholder (ADR-0018); CI stamps the tag name at
release.
"""

from .paths import Paths

# The package's public surface: the install layout type and the
# user-facing install failure. (The explicit __all__ marks Paths as a
# re-export of the paths.py alias; InstallError and __version__ are
# defined in this module.)
__all__ = ["InstallError", "Paths", "__version__"]

__version__ = "0.0.0.dev0"


class InstallError(Exception):
    """User-facing failure of the install/bootstrap flow."""

    pass
