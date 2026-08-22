"""The invalid-invocation dispatch signal of the modus-operandi launcher."""


class InvalidInvocation(Exception):
    """build_command saw an unusable invocation: print usage on stderr and exit
    non-zero."""
