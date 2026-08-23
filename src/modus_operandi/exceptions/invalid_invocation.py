"""The invalid-invocation dispatch signal of the modus-operandi launcher."""


class InvalidInvocation(Exception):
    """build_command saw an unusable invocation: print the reason (when given)
    and usage on stderr and exit non-zero."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
