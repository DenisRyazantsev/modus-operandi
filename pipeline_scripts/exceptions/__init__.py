"""Exceptions signalling the spec-run subcommand dispatch.

One class per file: help_requested.py, invalid_invocation.py,
edit_requested.py. This package is copied next to the installed launcher
(spec-run) so the submodules stay importable wherever the launcher runs.
"""

from exceptions.edit_requested import EditRequested
from exceptions.help_requested import HelpRequested
from exceptions.invalid_invocation import InvalidInvocation

__all__ = ["EditRequested", "HelpRequested", "InvalidInvocation"]
