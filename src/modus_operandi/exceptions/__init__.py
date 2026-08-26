"""Exceptions signalling the modus-operandi subcommand dispatch.

One class per file: edit_requested.py, help_requested.py,
invalid_invocation.py, uninstall_requested.py, version_requested.py.
"""

from modus_operandi.exceptions.edit_requested import EditRequested
from modus_operandi.exceptions.help_requested import HelpRequested
from modus_operandi.exceptions.invalid_invocation import InvalidInvocation
from modus_operandi.exceptions.uninstall_requested import UninstallRequested
from modus_operandi.exceptions.version_requested import VersionRequested

__all__ = [
    "EditRequested",
    "HelpRequested",
    "InvalidInvocation",
    "UninstallRequested",
    "VersionRequested",
]
