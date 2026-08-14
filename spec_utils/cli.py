"""CLI: argument parsing, orchestration, entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import (
    CONFIG_EXAMPLE,
    REPO_ROOT,
    InstallError,
    Paths,
    config,
    deps,
    register,
    render,
    uninstall,
    verify,
)


def print_instructions(paths: Paths) -> None:
    print(
        "\nDone. Next steps:\n"
        "  1. Edit {} to choose your models "
        "(planner = strong, executor = cheap), then rerun install.py.\n"
        "  2. In any project run:\n"
        "       specify workflow run {} -i feature=\"your feature description\"\n"
        "     or, from a Spec Kit project (run 'specify init' first), install by ID once:\n"
        "       python3 {} --register\n"
        "     and then:\n"
        "       specify workflow run adr-pipeline -i feature=\"...\"\n"
        "     or review your code (default: whole codebase):\n"
        "       specify workflow run review-pipeline\n"
        "     or review only the changes between branches:\n"
        "       specify workflow run review-pipeline -i branch-diff=true\n"
        "  3. If the run pauses at a gate, review and resume with:\n"
        "       specify workflow resume <run_id>\n".format(
            paths["config"], paths["workflow"], REPO_ROOT / "install.py"
        )
    )


def collect_keys(data: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in (data or {}).items():
        full = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            keys.update(collect_keys(value, full))
        else:
            keys.add(full)
    return keys


def print_diff_new_options(config_path: str | Path, cfg: dict[str, Any]) -> None:
    # --update feature: compare the example config against the user's raw
    # config (before apply_defaults, which fills every key) and report the
    # options the user is not setting yet.
    example = deps.yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8")) or {}
    new = collect_keys(example) - collect_keys(cfg)
    if new:
        print(f"new options available (not yet set in {config_path}):")
        for key in sorted(new):
            print(f"  {key}")


def validate_args(args: argparse.Namespace) -> None:
    # Parse-time flag-combination rules; run_install itself assumes a valid
    # combination.
    if args.register:
        if args.home:
            raise InstallError("--register cannot be combined with --home")
        if args.uninstall or args.update:
            raise InstallError(
                "--register cannot be combined with --uninstall/--update"
            )
    if args.uninstall and args.update:
        raise InstallError("--uninstall cannot be combined with --update")


def run_install(args: argparse.Namespace) -> None:
    home = Path(args.home).expanduser() if args.home else Path.home()
    paths = config.build_paths(home)
    if args.register:
        register.do_register(paths)
        return
    if args.uninstall:
        uninstall.do_uninstall(paths, args.yes)
        return

    print("spec-kit-llm-client installer")
    deps.check_prerequisites()
    deps.ensure_pyyaml()
    deps.ensure_specify()
    for directory in (paths["agents"], paths["scripts"], paths["config_dir"]):
        directory.mkdir(parents=True, exist_ok=True)
    config.ensure_config(paths)
    raw = config.load_config(paths["config"])
    cfg = config.validate_config(config.apply_defaults(raw))
    if args.update:
        # Diff against the raw config, not the defaults-filled one: after
        # apply_defaults() every key exists, so the diff would always be empty.
        print_diff_new_options(paths["config"], raw)
    render.render_agents(cfg, paths)
    render.render_run_agent(cfg, paths)
    render.render_name_task(cfg, paths)
    render.render_run_pipeline(paths)
    render.render_adr_scripts(paths)
    render.render_workflow(cfg, paths)
    render.render_review_workflow(cfg, paths)
    verify.verify_install(paths)
    print("installation verified")
    print_instructions(paths)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
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


def main(argv: Sequence[str] | None = None) -> int:
    # YAML parse errors are already wrapped into InstallError by
    # config.load_config; everything else here is a user-facing failure.
    try:
        args = parse_args(argv)
        validate_args(args)
        run_install(args)
    except (InstallError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
