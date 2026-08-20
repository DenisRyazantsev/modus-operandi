"""Install orchestration: the full install flow.

User-facing status lines and the next-steps instructions are printed by the
dev CLI layer (installer_cli.py); this module only drives the flow.
``apply()`` renders every artifact from the package data and records
``install-version.txt`` so the rendered files always correspond to the
installed package version; the full post-install verification
(``verify.verify_install``) runs only in the dev flow (``install()``), never
in the launcher bootstrap.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

from . import Paths, __version__, config, render, verify


def ensure_config(paths: Paths) -> bool:
    """Provision the config files; returns whether config.yml was created.

    The config.example.yml reference copy is always refreshed from the
    package data; config.yml is created from the example only when missing —
    the user's config is never overwritten.
    """
    example = files("spec_run").joinpath("data/config.example.yml").read_bytes()
    paths["config_example"].write_bytes(example)
    if not paths["config"].exists():
        paths["config"].write_bytes(example)
        return True
    return False


def apply(paths: Paths) -> tuple[bool, dict[str, Any]]:
    """Re-render every artifact from the current config.

    Returns ``(created_config, validated_cfg)``. The bootstrap, ``spec-run
    edit`` and the dev install flow all call this; ``install-version.txt`` is
    written at the end (the single place the marker is recorded), so the
    rendered artifacts always correspond to the installed package version.
    The config is loaded and validated again, so an invalid edit fails here
    (raised as InstallError) instead of silently applying stale artifacts.
    """
    for directory in (paths["agents"], paths["scripts"], paths["config_dir"]):
        directory.mkdir(parents=True, exist_ok=True)
    created = ensure_config(paths)
    raw = config.load_config(paths["config"])
    cfg = config.validate_config(config.apply_defaults(raw))
    render.render_agents(cfg, paths)
    render.render_role_bodies(paths)
    render.render_run_agent(paths)
    render.render_name_task(paths)
    render.render_run_pipeline(paths)
    render.render_victory_wav(paths)
    render.render_adr_scripts(paths)
    render.render_step_scripts(paths)
    render.render_review_workflow(cfg, paths)
    render.render_task_workflow(cfg, paths)
    render.render_prompts(paths)
    paths["install_version"].write_text(__version__, encoding="utf-8")
    return created, cfg


def install(paths: Paths) -> tuple[bool, dict[str, Any]]:
    """The dev install flow: prerequisites, apply, then full verification.

    ``verify_install`` (installed-file checks, workflow syntax probe, agent
    visibility) runs only here, never in the launcher bootstrap.
    """
    verify.check_prerequisites(paths)
    created, cfg = apply(paths)
    verify.verify_install(paths, cfg)
    return created, cfg
