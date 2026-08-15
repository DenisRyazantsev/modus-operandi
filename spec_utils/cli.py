"""CLI: argument parsing, flag validation, dispatch and error mapping."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import REPO_ROOT, InstallError, Paths, installer, paths, register, uninstall


def print_instructions(layout: Paths) -> None:
    print(
        "\nDone. Next steps:\n"
        "  1. Edit {} to choose your models "
        "(planner = strong, executor = cheap), then rerun install.py.\n"
        "  2. In any project run (no `specify init` or --register needed):\n"
        '       spec-run adr "your feature description"\n'
        "     or review your code (default: whole codebase):\n"
        "       spec-run review\n"
        "     or review only the changes between branches:\n"
        "       spec-run review --branch-diff\n"
        "     or, from a Spec Kit project (run 'specify init' first), install by ID once:\n"
        "       python3 {} --register\n"
        "     and then:\n"
        '       specify workflow run adr-pipeline -i feature="..."\n'
        "     or review your code (default: whole codebase):\n"
        "       specify workflow run review-pipeline\n"
        "     or review only the changes between branches:\n"
        "       specify workflow run review-pipeline -i branch-diff=true\n"
        "  3. If the run pauses at a gate, review and resume with:\n"
        "       specify workflow resume <run_id>\n".format(
            layout["config"], REPO_ROOT / "install.py"
        )
    )


def print_path_warning(layout: Paths) -> None:
    # The launcher resolves only when its bin directory is on PATH. The
    # installer never edits shell configs: print a warning with the two
    # workarounds (add the directory to PATH, or call the launcher by its
    # full path). The install itself already succeeded.
    bin_dir = layout["user_bin"]
    if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        print(
            "\nwarning: {} is not on your PATH - add it (e.g. "
            'export PATH="$HOME/.local/bin:$PATH") or call the launcher by '
            "its full path: {}".format(bin_dir, layout["spec_run"])
        )


def print_register_usage() -> None:
    print('run them with: specify workflow run adr-pipeline -i feature="..."')
    print("or: specify workflow run review-pipeline -i branch-diff=true")
    print("    (default: whole codebase; branch-diff=true: only the changes")
    print("    between the current branch and the default branch)")


def validate_args(args: argparse.Namespace) -> None:
    # Parse-time flag-combination rules; the dispatcher assumes a valid
    # combination.
    if args.register:
        if args.home:
            raise InstallError("--register cannot be combined with --home")
        if args.uninstall or args.update:
            raise InstallError("--register cannot be combined with --uninstall/--update")
    if args.uninstall and args.update:
        raise InstallError("--uninstall cannot be combined with --update")


def dispatch(args: argparse.Namespace) -> None:
    home = Path(args.home).expanduser() if args.home else Path.home()
    layout = paths.build_paths(home)
    if args.register:
        register.do_register(layout)
        print_register_usage()
        return
    if args.uninstall:
        uninstall.do_uninstall(layout, args.yes)
        return
    print("spec-kit-llm-client installer")
    installer.install(layout, args.update)
    print("installation verified")
    print_path_warning(layout)
    print_instructions(layout)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the spec-kit-llm-client planner/executor pipeline"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="reinstall templates and print newly available config options",
    )
    parser.add_argument("--uninstall", action="store_true", help="remove installed files")
    parser.add_argument(
        "--register",
        action="store_true",
        help="install the workflow by ID into the current Spec Kit project",
    )
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
        validate_args(args)
        dispatch(args)
    except (InstallError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
