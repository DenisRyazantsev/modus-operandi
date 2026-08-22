"""Bootstrap: materialize the rendered installation on first run / update.

One responsibility: check the ``install-version.txt`` marker against the
package ``__version__`` and, when the rendered artifacts are missing or
stale, render them from the package data (prerequisites check + apply) and
report one status line. The launcher (cli.py) owns the argument parsing and
dispatch; this module owns the installation state — it changes together with
installer/verify, not with the command surface.
"""

from __future__ import annotations

import sys

from . import InstallError, Paths, __version__, installer, verify


def ensure_installed(layout: Paths) -> int:
    """Bootstrap the rendered installation from the package data.

    Reads ``install-version.txt`` (config base /modus-operandi/install-version.txt):
    when the file is missing or its version differs from the package
    ``__version__``, checks the prerequisites and renders every artifact from
    the package data (``apply()`` records the marker), then prints exactly
    one status line. Returns 0 on success (including an up-to-date
    installation) and 1 on error, with the reason on stderr.
    """
    marker = layout["install_version"]
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == __version__:
        return 0
    was_installed = marker.exists()
    try:
        verify.check_prerequisites(layout)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        installer.apply(layout)
    except (InstallError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if was_installed:
        print(f"modus-operandi: updated to {__version__}", flush=True)
    else:
        print(f"modus-operandi: installed to {layout['config_dir']}", flush=True)
    return 0
