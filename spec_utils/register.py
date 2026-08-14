"""Register: install the rendered workflows into the current Spec Kit project."""

from __future__ import annotations

from pathlib import Path

from . import InstallError, Paths, deps


def do_register(paths: Paths) -> None:
    if not paths["workflow"].exists():
        raise InstallError("adr-pipeline.yml not found - run install.py first")
    if not paths["review_workflow"].exists():
        raise InstallError("review-pipeline.yml not found - run install.py first")
    specify = deps.find_in_path("specify")
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
        deps.run([specify, "workflow", "add", str(path), "--dev"])
        print(f"installed '{name}' into this project")
    print('run them with: specify workflow run adr-pipeline -i feature="..."')
    print('or: specify workflow run review-pipeline -i branch-diff=true')
    print("    (default: whole codebase; branch-diff=true: only the changes")
    print("    between the current branch and the default branch)")
