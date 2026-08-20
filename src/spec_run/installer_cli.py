"""CLI of the dev install flow: argument parsing and dispatch for install.py.

Only the dev flow (``install.py --home/--yes/--uninstall``) goes through
this module; the launcher's ``spec-run`` console script lives in cli.py.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import InstallError, Paths, installer, paths, uninstall


def print_instructions(layout: Paths) -> None:
    print(
        "\nDone. Next steps:\n"
        "  1. Edit {} to choose your models "
        "(planner = strong, executor = cheap), then rerun install.py, or\n"
        "     re-apply the changes in one go with `spec-run edit`.\n"
        "  2. In any project run (no `specify init` required):\n"
        '       spec-run task "your task description"\n'
        "     or review your code (default: whole codebase):\n"
        "       spec-run review\n"
        "     or review only the changes between branches:\n"
        "       spec-run review --branch-diff\n"
        "     or open the installed config in your editor and apply it on exit:\n"
        "       spec-run edit\n"
        "  3. If the run pauses at a gate, review and resume with:\n"
        "       specify workflow resume <run_id>\n".format(layout["config"])
    )


def dispatch(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser() if args.home else Path.home()
    layout = paths.build_paths(home)
    if args.uninstall:
        return uninstall.do_uninstall(layout, args.yes)
    print("spec-run installer")
    created, _ = installer.install(layout)
    if created:
        print(f"created {layout['config']} with defaults (edit it to change models)")
    print("installation verified")
    print_instructions(layout)
    return 0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the spec-run planner/executor pipeline (dev flow)"
    )
    parser.add_argument("--uninstall", action="store_true", help="remove installed files")
    parser.add_argument(
        "--home",
        metavar="DIR",
        help="base directory instead of the real home (used by tests)",
    )
    parser.add_argument("--yes", action="store_true", help="answer yes to all prompts")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    # YAML parse errors are already wrapped into InstallError by
    # config.load_config; everything else here is a user-facing failure.
    try:
        args = parse_args(argv)
        return dispatch(args)
    except (InstallError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
