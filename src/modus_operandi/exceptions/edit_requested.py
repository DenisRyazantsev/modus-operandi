"""The `edit` dispatch signal of the modus-operandi launcher."""


class EditRequested(Exception):
    """build_command saw `edit`: open the installed config in the editor and
    re-apply it on exit (handled by the caller through _run_edit)."""
