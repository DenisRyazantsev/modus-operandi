"""Turn the installed config.yml + argv into the specify invocation and env.

One responsibility: map the runtime config (MO_CONFIG or the derived
config.yml) and the CLI arguments to the launch of specify. No run-side I/O
happens here beyond reading the config file itself; run_pipeline.py only
orchestrates the live run from the returned (cmd, env, state_dir, logs_dir).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# The installed config.yml: the only runtime source of the workflow settings
# (state_dir, adr_dir, use_serve, human_gates). `__file__` is the installed
# module (~/.config/opencode/scripts/config_invocation.py), so ~/.config is
# three `.parent` hops up from it: scripts/ -> opencode/ -> .config/.
# MO_CONFIG overrides the location (used by tests).
CONFIG_PATH = Path(
    os.environ.get("MO_CONFIG")
    or (Path(__file__).resolve().parent.parent.parent / "modus-operandi" / "config.yml")
)

# Supported backends; "opencode" is the default (config default and the
# fallback for an invalid config value).
BACKENDS = ("opencode", "cursor")


def normalize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Fold the legacy top-level `models:` into `opencode.models`.

    The installer does the same at install time (modus_operandi/config.py,
    including dropping the legacy key when an explicit opencode section
    exists); the wrapper must mirror it so existing configs keep delivering
    the models at runtime too.
    """
    cfg = dict(cfg)
    if "models" in cfg:
        if "opencode" not in cfg:
            cfg["opencode"] = {"models": cfg["models"]}
        cfg.pop("models", None)
    return cfg


def effective_backend(cfg: dict[str, Any], cli_backend: str | None) -> str:
    """Effective backend: the --backend CLI flag wins over the config key,
    which defaults to opencode. An invalid value in either place degrades to
    the config/default instead of failing the run.
    """
    if cli_backend in BACKENDS:
        return cli_backend
    backend = cfg.get("backend")
    return backend if backend in BACKENDS else "opencode"


def role_model(cfg: dict[str, Any], backend: str, role: str) -> str:
    """Model slug of a role under the active backend ("" when unset).

    The opencode agent files carry the opencode model; the exported value is
    only consumed by the cursor branch of run-agent.sh/name-task.sh.
    """
    section = cfg.get("cursor") if backend == "cursor" else cfg.get("opencode")
    models = (section or {}).get("models") or {}
    model = (models.get(role) or {}).get("model")
    return model if isinstance(model, str) else ""


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Read the installed config.yml into a dict, or {} on any failure.

    config_path defaults to the module's CONFIG_PATH; the run-pipeline entry
    passes its own CONFIG_PATH explicitly so a runtime override (e.g. tests
    pointing the wrapper at another file) is honored. A missing or unreadable
    file degrades to the documented defaults, so a hand-invoked wrapper (or a
    config deleted after install) still runs.
    """
    path = config_path if config_path is not None else CONFIG_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import yaml  # pyproject.toml declares pyyaml as a package dependency

        data = yaml.safe_load(text) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def build_specify_invocation(
    cfg: dict[str, Any], source: str, extra: list[str], cli_backend: str | None = None
) -> tuple[list[str], dict[str, str], str, Path]:
    """Map the installed config + argv to the specify invocation.

    The single place that turns config.yml into the launch of specify;
    returns (specify_cmd, env, state_dir, logs_dir) so main() only
    orchestrates the live run. No run-side I/O happens here:

    - state_dir/adr_dir go to the workflow as -i inputs (its steps reference
      {{ inputs.state_dir }} / {{ inputs.adr_dir }});
    - use_serve becomes the MO_ATTACH_FLAG env var for
      run-agent.sh/name-task.sh;
    - the effective backend (cli_backend > config `backend:` > opencode) is
      exported as MO_BACKEND together with the role models of the active
      backend (MO_PLANNER_MODEL/MO_EXECUTOR_MODEL) for
      run-agent.sh/name-task.sh;
    - human_gates decides whether the gate verdict inputs are passed as
      empty (interactive) or left to their defaults (auto-approve): the
      adr-pipeline's ADR gate binds adr_verdict, the task-pipeline's
      motivation gate binds motivation_verdict;
    - run-agent.sh keeps its sessions/logs/pids under the same state dir the
      workflow steps write artifacts to, so it must see MO_STATE_DIR.
    """
    cfg = normalize_config(cfg)
    backend = effective_backend(cfg, cli_backend)
    workflow = cfg.get("workflow") or {}
    state_dir = workflow.get("state_dir") or ".workflow"
    adr_dir = workflow.get("adr_dir") or "architecture"
    use_serve = bool(workflow.get("use_serve", False))
    human_gates = bool(workflow.get("human_gates", True))
    # `source` is argv[0] — the raw workflow path the user passed (e.g.
    # ~/.config/modus-operandi/task-pipeline.yml) or a bare id in tests,
    # so only a substring test matches both forms; an exact match or an
    # explicit flag would not. The else branch below intentionally keeps the
    # legacy behavior of always passing adr_verdict, which review-pipeline
    # tolerates as an undeclared input.
    is_task_pipeline = "task-pipeline" in str(source)
    attach_flag = "--attach http://localhost:4096" if use_serve else ""
    scripts_dir = str(Path(__file__).resolve().parent)
    env = dict(os.environ)
    env["MO_SCRIPTS_DIR"] = scripts_dir
    env["MO_ATTACH_FLAG"] = attach_flag
    env["MO_STATE_DIR"] = state_dir
    env["MO_BACKEND"] = backend
    env["MO_PLANNER_MODEL"] = role_model(cfg, backend, "planner")
    env["MO_EXECUTOR_MODEL"] = role_model(cfg, backend, "executor")

    specify_cmd = [
        "specify",
        "workflow",
        "run",
        source,
        "-i",
        f"state_dir={state_dir}",
        "-i",
        f"adr_dir={adr_dir}",
    ]
    if human_gates:
        # Interactive gates: an empty verdict input falls through to the
        # human prompt. Non-interactive runs omit it, so the declared
        # defaults auto-approve the gates (matching human_gates: false).
        if is_task_pipeline:
            specify_cmd += ["-i", "motivation_verdict="]
        else:
            specify_cmd += ["-i", "adr_verdict="]
    specify_cmd += extra

    logs_dir = Path.cwd() / state_dir / "logs"
    return specify_cmd, env, state_dir, logs_dir
