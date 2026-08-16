"""Turn the installed config.yml + argv into the specify invocation and env.

One responsibility: map the runtime config (SKLC_CONFIG or the derived
config.yml) and the CLI arguments to the launch of specify. No run-side I/O
happens here beyond reading the config file itself; run_pipeline.py only
orchestrates the live run from the returned (cmd, env, state_dir, logs_dir).
"""

from __future__ import annotations

import os
from pathlib import Path

# The installed config.yml: the only runtime source of the workflow settings
# (state_dir, adr_dir, use_serve, human_gates). `__file__` is the installed
# module (~/.config/opencode/scripts/config_invocation.py), so ~/.config is
# three `.parent` hops up from it: scripts/ -> opencode/ -> .config/.
# SKLC_CONFIG overrides the location (used by tests).
CONFIG_PATH = Path(
    os.environ.get("SKLC_CONFIG")
    or (Path(__file__).resolve().parent.parent.parent / "spec-kit-llm-client" / "config.yml")
)

# Supported backends; "opencode" is the default (config default and the
# fallback for an invalid config value).
BACKENDS = ("opencode", "cursor")


def normalize_config(cfg: dict) -> dict:
    """Fold the legacy top-level `models:` into `opencode.models`.

    The installer does the same at install time (spec_utils/config.py,
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


def effective_backend(cfg: dict, cli_backend: str | None) -> str:
    """Effective backend: the --backend CLI flag wins over the config key,
    which defaults to opencode. An invalid value in either place degrades to
    the config/default instead of failing the run.
    """
    if cli_backend in BACKENDS:
        return cli_backend
    backend = cfg.get("backend")
    return backend if backend in BACKENDS else "opencode"


def role_model(cfg: dict, backend: str, role: str) -> str:
    """Model slug of a role under the active backend ("" when unset).

    The opencode agent files carry the opencode model; the exported value is
    only consumed by the cursor branch of run-agent.sh/name-task.sh.
    """
    section = cfg.get("cursor") if backend == "cursor" else cfg.get("opencode")
    models = (section or {}).get("models") or {}
    model = (models.get(role) or {}).get("model")
    return model if isinstance(model, str) else ""


def load_config(config_path: Path | None = None) -> dict:
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
        import yaml  # installed by the installer (deps.ensure_pyyaml)

        data = yaml.safe_load(text) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def build_specify_invocation(
    cfg: dict, source: str, extra: list[str], cli_backend: str | None = None
) -> tuple[list[str], dict[str, str], str, Path]:
    """Map the installed config + argv to the specify invocation.

    The single place that turns config.yml into the launch of specify;
    returns (specify_cmd, env, state_dir, logs_dir) so main() only
    orchestrates the live run. No run-side I/O happens here:

    - state_dir/adr_dir go to the workflow as -i inputs (its steps reference
      {{ inputs.state_dir }} / {{ inputs.adr_dir }});
    - use_serve becomes the SKLC_ATTACH_FLAG env var for
      run-agent.sh/name-task.sh;
    - the effective backend (cli_backend > config `backend:` > opencode) is
      exported as SKLC_BACKEND together with the role models of the active
      backend (SKLC_PLANNER_MODEL/SKLC_EXECUTOR_MODEL) for
      run-agent.sh/name-task.sh;
    - human_gates decides whether the ADR gate's verdict input is passed as
      empty (interactive) or left to its "approve" default (auto-approve);
    - run-agent.sh keeps its sessions/logs/pids under the same state dir the
      workflow steps write artifacts to, so it must see SKLC_STATE_DIR.
    """
    cfg = normalize_config(cfg)
    backend = effective_backend(cfg, cli_backend)
    workflow = cfg.get("workflow") or {}
    state_dir = workflow.get("state_dir") or ".workflow"
    adr_dir = workflow.get("adr_dir") or "architecture"
    use_serve = bool(workflow.get("use_serve", False))
    human_gates = bool(workflow.get("human_gates", True))
    attach_flag = "--attach http://localhost:4096" if use_serve else ""
    scripts_dir = str(Path(__file__).resolve().parent)
    env = dict(os.environ)
    env["SKLC_SCRIPTS_DIR"] = scripts_dir
    env["SKLC_ATTACH_FLAG"] = attach_flag
    env["SKLC_STATE_DIR"] = state_dir
    env["SKLC_BACKEND"] = backend
    env["SKLC_PLANNER_MODEL"] = role_model(cfg, backend, "planner")
    env["SKLC_EXECUTOR_MODEL"] = role_model(cfg, backend, "executor")

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
        # Interactive gates: an empty adr_verdict falls through to the human
        # prompt. Non-interactive runs omit it, so the declared default
        # "approve" auto-approves the ADR gate (matching human_gates: false).
        specify_cmd += ["-i", "adr_verdict="]
    specify_cmd += extra

    logs_dir = Path.cwd() / state_dir / "logs"
    return specify_cmd, env, state_dir, logs_dir
