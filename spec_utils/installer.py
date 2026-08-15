"""Install orchestration: the full install flow.

User-facing status lines and the next-steps instructions are printed by the
CLI layer (cli.py); this module only drives the flow.
"""

from __future__ import annotations

import shutil

from . import CONFIG_EXAMPLE, REPO_ROOT, Paths, config, config_diff, deps, render, verify

# Recommended .gitignore lines for a project using the pipeline (documentation
# role only; the installer does not write .gitignore files).
GITIGNORE_SNIPPET = ".workflow/\n.specify/workflows/\n"


def ensure_config(paths: Paths) -> None:
    # File provisioning: the config.example.yml reference copy and the first
    # config.yml (which the user edits to pick models). config.py stays
    # limited to loading/merging/validating, so the copies live here next to
    # the directory mkdir orchestration.
    shutil.copy2(CONFIG_EXAMPLE, paths["config_example"])
    if not paths["config"].exists():
        shutil.copy2(CONFIG_EXAMPLE, paths["config"])
        print("created {} with defaults (edit it to change models)".format(paths["config"]))


def apply(paths: Paths, update: bool = False) -> None:
    # Re-render every artifact from the current config without the install-time
    # prerequisite/dependency checks and without the next-steps output: this is
    # the `install.py --apply` mode used by `spec-run edit` after the user
    # leaves the editor. The config is loaded and validated again, so an
    # invalid edit fails here (raised as InstallError) instead of silently
    # applying stale artifacts.
    for directory in (paths["agents"], paths["scripts"], paths["config_dir"], paths["user_bin"]):
        directory.mkdir(parents=True, exist_ok=True)
    ensure_config(paths)
    raw = config.load_config(paths["config"])
    cfg = config.validate_config(config.apply_defaults(raw))
    if update:
        # Diff against the raw config, not the defaults-filled one: after
        # apply_defaults() every key exists, so the diff would always be empty.
        config_diff.report_new_options(paths, raw)
    render.render_agents(cfg, paths)
    render.render_run_agent(paths)
    render.render_name_task(paths)
    render.render_run_pipeline(paths)
    render.render_victory_wav(paths)
    render.render_adr_scripts(paths)
    render.render_workflow(cfg, paths)
    render.render_review_workflow(cfg, paths)
    render.render_spec_run(paths)
    # Record the repo's install.py path: `spec-run edit` re-applies the config
    # through it, and the path cannot be derived from the installed launcher.
    paths["install_path"].write_text(str(REPO_ROOT / "install.py"), encoding="utf-8")
    verify.verify_install(paths)


def install(paths: Paths, update: bool) -> None:
    verify.check_prerequisites()
    deps.ensure_pyyaml()
    deps.ensure_specify()
    apply(paths, update)
