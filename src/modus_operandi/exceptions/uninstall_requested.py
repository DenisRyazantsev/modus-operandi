"""The `uninstall` dispatch signal of the modus-operandi launcher."""


class UninstallRequested(Exception):
    """build_command saw `uninstall`: remove the rendered pipeline files.

    Carries the optional `--yes` flag that skips the confirmation prompt.
    """

    def __init__(self, yes: bool = False) -> None:
        super().__init__()
        self.yes = yes
