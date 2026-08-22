"""The run-pipeline.py wrapper's CLI surface: argv -> the specify invocation.

One responsibility: own the wrapper's command-line surface — the optional
leading `--backend` flag, the workflow source plus the extra specify args,
the usage text and the error messages/exit codes. run_pipeline.py only
calls parse_cli and orchestrates the run; a CLI-surface change touches
only this file (mirroring the package's own cli.py / installer_cli.py
separation).
"""

from __future__ import annotations

import sys

from config_invocation import BACKENDS

# The usage text printed for -h/--help and an empty argv: the command
# surface of the wrapper. The full documentation (environment, pty
# behavior, output format) lives in run_pipeline.py's module docstring.
USAGE = """\
Usage: run-pipeline.py <workflow-id-or-path> [extra specify args...]
  run-pipeline.py review-pipeline
  run-pipeline.py task-pipeline -i task="..."
  run-pipeline.py ~/.config/modus-operandi/review-pipeline.yml -i branch-diff=true
  run-pipeline.py --backend cursor task-pipeline -i task="..."   # backend override
"""


def parse_cli(argv: list[str]) -> tuple[str | None, str, list[str]] | int:
    """Parse the wrapper's argv into (cli_backend, source, extra), or an exit code.

    The optional leading `--backend <opencode|cursor>` flag is validated
    and consumed before the workflow source; the remaining argv is the
    source plus the extra specify args. An unusable invocation prints its
    message here and returns the exit code: empty argv and -h/--help print
    the usage (0), a bad --backend prints the error (1). CLI surface
    changes stay in this one function, away from the orchestration body.
    """
    cli_backend: str | None = None
    if argv and argv[0] == "--backend":
        # A leading global flag (modus-operandi puts it in front of the workflow
        # source): overrides the configured backend for this run.
        if len(argv) < 2:
            print("error: --backend requires a value (opencode or cursor)", file=sys.stderr)
            return 1
        cli_backend = argv[1]
        if cli_backend not in BACKENDS:
            print(
                f"error: invalid --backend value '{cli_backend}'; use 'opencode' or 'cursor'",
                file=sys.stderr,
            )
            return 1
        argv = argv[2:]
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    return cli_backend, argv[0], argv[1:]
