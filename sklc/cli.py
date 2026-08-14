"""CLI: argument parsing, orchestration, entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import REPO_ROOT, InstallError
from . import actions, config, deps, render, verify


def print_instructions(paths):
    print(
        "\nDone. Next steps:\n"
        "  1. Edit %s to choose your models "
        "(planner = strong, executor = cheap), then rerun install.py.\n"
        "  2. In any project run:\n"
        "       specify workflow run %s -i feature=\"your feature description\"\n"
        "     or, from a Spec Kit project (run 'specify init' first), install by ID once:\n"
        "       python3 %s --register\n"
        "     and then:\n"
        "       specify workflow run adr-pipeline -i feature=\"...\"\n"
        "  3. If the run pauses at a gate, review and resume with:\n"
        "       specify workflow resume <run_id>\n"
        % (paths["config"], paths["workflow"], REPO_ROOT / "install.py")
    )


def run_install(args):
    home = Path(args.home).expanduser() if args.home else Path.home()
    paths = config.build_paths(home)
    if args.register:
        if args.home:
            raise InstallError("--register cannot be combined with --home")
        if args.uninstall or args.update:
            raise InstallError(
                "--register cannot be combined with --uninstall/--update"
            )
        actions.do_register(paths)
        return
    if args.uninstall and args.update:
        raise InstallError("--uninstall cannot be combined with --update")
    if args.uninstall:
        actions.do_uninstall(paths, args.yes)
        return

    print("spec-kit-llm-client installer")
    if not deps.find_in_path("python3"):
        raise InstallError("python3 not found in PATH")
    if not deps.find_in_path("opencode"):
        raise InstallError(
            "opencode not found in PATH - install it first (https://opencode.ai/docs)"
        )
    deps.ensure_pyyaml()
    deps.ensure_specify()
    for directory in (paths["agents"], paths["scripts"], paths["sklc"]):
        directory.mkdir(parents=True, exist_ok=True)
    config.ensure_config(paths)
    cfg = config.validate_config(config.load_config(paths["config"]))
    if args.update:
        config.print_diff_new_options(paths["config"], cfg)
    render.render_agents(cfg, paths)
    render.render_run_agent(cfg, paths)
    render.render_workflow(cfg, paths)
    verify.validate_install(paths)
    print("installation verified")
    print_instructions(paths)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Install the spec-kit-llm-client planner/executor pipeline"
    )
    parser.add_argument(
        "--update", action="store_true",
        help="reinstall templates and print newly available config options",
    )
    parser.add_argument(
        "--uninstall", action="store_true", help="remove installed files"
    )
    parser.add_argument(
        "--register", action="store_true",
        help="install the workflow by ID into the current Spec Kit project",
    )
    parser.add_argument(
        "--home", metavar="DIR",
        help="base directory instead of the real home (used by tests)",
    )
    parser.add_argument(
        "--yes", action="store_true", help="answer yes to all prompts"
    )
    return parser.parse_args(argv)


def main(argv=None):
    try:
        run_install(parse_args(argv))
    except InstallError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except Exception as exc:
        if deps.yaml is not None and isinstance(exc, deps.yaml.YAMLError):
            print("error: %s" % exc, file=sys.stderr)
            return 1
        raise
    return 0
