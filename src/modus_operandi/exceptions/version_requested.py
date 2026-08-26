"""The `--version`/`-V` dispatch signal of the modus-operandi launcher."""


class VersionRequested(Exception):
    """build_command saw `--version`/`-V`: print the version on stdout and exit 0."""
