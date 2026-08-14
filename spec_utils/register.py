"""Register: install the rendered workflows into the current Spec Kit project.

The usage instructions after a successful register are printed by the CLI
dispatcher (cli.py); this module only performs the registration.
"""

from __future__ import annotations

from pathlib import Path

from . import InstallError, Paths, proc, tool_discovery


def do_register(paths: Paths) -> None:
    if not paths["workflow"].exists():
        raise InstallError("adr-pipeline.yml not found - run install.py first")
    if not paths["review_workflow"].exists():
        raise InstallError("review-pipeline.yml not found - run install.py first")
    specify = tool_discovery.find_in_path("specify")
    if not specify:
        raise InstallError("'specify' not found on PATH - run install.py first")
    if not Path(".specify").exists():
        raise InstallError(
            "not a Spec Kit project (no .specify/ directory); run 'specify init' first"
        )
    for name, path in (
        ("adr-pipeline", paths["workflow"]),
        ("review-pipeline", paths["review_workflow"]),
    ):
        proc.run([specify, "workflow", "add", str(path), "--dev"])
        print(f"installed '{name}' into this project")
