"""The invalid-invocation dispatch signal of the spec-run launcher."""


class InvalidInvocation(Exception):
    """build_command saw an unusable invocation: print usage on stderr and exit
    non-zero."""
