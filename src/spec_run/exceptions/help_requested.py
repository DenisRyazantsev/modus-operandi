"""The `--help`/`-h` dispatch signal of the spec-run launcher."""


class HelpRequested(Exception):
    """build_command saw `--help`/`-h`: print usage on stdout and exit 0."""
