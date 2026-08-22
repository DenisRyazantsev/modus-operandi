"""Exceptions signalling the modus-operandi subcommand dispatch.

One class per file: help_requested.py, invalid_invocation.py,
edit_requested.py, uninstall_requested.py.
"""

from modus_operandi.exceptions.edit_requested import EditRequested
from modus_operandi.exceptions.help_requested import HelpRequested
from modus_operandi.exceptions.invalid_invocation import InvalidInvocation
from modus_operandi.exceptions.uninstall_requested import UninstallRequested

__all__ = [
    "EditRequested",
    "HelpRequested",
    "InvalidInvocation",
    "UninstallRequested",
]
