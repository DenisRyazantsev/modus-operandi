"""Exceptions signalling the spec-run subcommand dispatch.

One class per file: help_requested.py, invalid_invocation.py,
edit_requested.py, uninstall_requested.py.
"""

from spec_run.exceptions.edit_requested import EditRequested
from spec_run.exceptions.help_requested import HelpRequested
from spec_run.exceptions.invalid_invocation import InvalidInvocation
from spec_run.exceptions.uninstall_requested import UninstallRequested

__all__ = [
    "EditRequested",
    "HelpRequested",
    "InvalidInvocation",
    "UninstallRequested",
]
