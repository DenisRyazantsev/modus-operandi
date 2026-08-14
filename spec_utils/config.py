"""Configuration: paths, defaults, config.yml loading and validation."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from . import CONFIG_EXAMPLE, InstallError, Paths, deps

DEFAULT_STATE_DIR = ".workflow"
DEFAULT_MAX_FIX_ITERATIONS = 5
DEFAULT_MAX_SRP_ITERATIONS = 5
DEFAULT_MAX_BUG_ITERATIONS = 5
DEFAULT_MAX_COMMENT_ITERATIONS = 5
DEFAULT_SHELL_TIMEOUT = 7200
DEFAULT_REASONING = "max"
DEFAULT_ADR_DIR = "architecture"

DEFAULT_CONFIG: dict[str, Any] = {
    "workflow": {
        "state_dir": DEFAULT_STATE_DIR,
        "max_fix_iterations": DEFAULT_MAX_FIX_ITERATIONS,
        "max_srp_iterations": DEFAULT_MAX_SRP_ITERATIONS,
        "max_bug_iterations": DEFAULT_MAX_BUG_ITERATIONS,
        "max_comment_iterations": DEFAULT_MAX_COMMENT_ITERATIONS,
        "shell_timeout": DEFAULT_SHELL_TIMEOUT,
        "adr_dir": DEFAULT_ADR_DIR,
        "human_gates": True,
        "use_serve": False,
    }
}


def build_paths(home: str | Path) -> Paths:
    base = Path(home)
    return {
        "agents": base / ".config" / "opencode" / "agent",
        "scripts": base / ".config" / "opencode" / "scripts",
        "config_dir": base / ".config" / "spec-kit-llm-client",
        "config": base / ".config" / "spec-kit-llm-client" / "config.yml",
        "config_example": base / ".config" / "spec-kit-llm-client" / "config.example.yml",
        "workflow": base / ".config" / "spec-kit-llm-client" / "adr-pipeline.yml",
        "review_workflow": base
        / ".config"
        / "spec-kit-llm-client"
        / "review-pipeline.yml",
        "run_agent": base / ".config" / "opencode" / "scripts" / "run-agent.sh",
        "run_pipeline": base
        / ".config"
        / "opencode"
        / "scripts"
        / "run-pipeline.sh",
        "save_adr": base / ".config" / "opencode" / "scripts" / "save_adr.py",
    }


def ensure_config(paths: Paths) -> None:
    shutil.copy2(CONFIG_EXAMPLE, paths["config_example"])
    if not paths["config"].exists():
        shutil.copy2(CONFIG_EXAMPLE, paths["config"])
        print("created {} with defaults (edit it to change models)".format(paths["config"]))


def load_config(path: str | Path) -> dict[str, Any]:
    # Config loading is the one place a YAML parse error can surface from user
    # input, so it is converted to InstallError here — main() then stays flat
    # without special-casing yaml types.
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        raw = deps.yaml.safe_load(text) or {}
    except Exception as exc:
        if deps.yaml is not None and isinstance(exc, deps.yaml.YAMLError):
            raise InstallError(f"invalid config.yml: {exc}") from exc
        raise
    return dict(raw)


def apply_defaults(raw: Any) -> dict[str, Any]:
    cfg = dict(raw or {})
    workflow = dict(DEFAULT_CONFIG["workflow"])
    workflow.update(cfg.get("workflow") or {})
    cfg["workflow"] = workflow
    cfg["models"] = cfg.get("models") or {}
    for role in ("planner", "executor"):
        model = dict(cfg["models"].get(role) or {})
        model.setdefault("reasoning", DEFAULT_REASONING)
        cfg["models"][role] = model
    return cfg


def validate_config(cfg: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    for role in ("planner", "executor"):
        model = cfg["models"].get(role) or {}
        for key in ("provider", "model", "reasoning"):
            value = model.get(key)
            if not value:
                errors.append(f"missing required key: models.{role}.{key}")
            elif "<" in str(value) or ">" in str(value):
                errors.append(
                    f"placeholder value in models.{role}.{key} - edit config.yml first"
                )
    workflow = cfg["workflow"]
    if (
        not isinstance(workflow.get("max_fix_iterations"), int)
        or workflow["max_fix_iterations"] < 1
    ):
        errors.append("workflow.max_fix_iterations must be an integer >= 1")
    if (
        not isinstance(workflow.get("max_srp_iterations"), int)
        or workflow["max_srp_iterations"] < 1
    ):
        errors.append("workflow.max_srp_iterations must be an integer >= 1")
    if (
        not isinstance(workflow.get("max_bug_iterations"), int)
        or workflow["max_bug_iterations"] < 1
    ):
        errors.append("workflow.max_bug_iterations must be an integer >= 1")
    if (
        not isinstance(workflow.get("max_comment_iterations"), int)
        or workflow["max_comment_iterations"] < 1
    ):
        errors.append("workflow.max_comment_iterations must be an integer >= 1")
    if not isinstance(workflow.get("shell_timeout"), int) or workflow["shell_timeout"] < 1:
        errors.append("workflow.shell_timeout must be a positive number of seconds")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(workflow.get("state_dir", ""))):
        errors.append("workflow.state_dir contains unsupported characters")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(workflow.get("adr_dir", ""))):
        errors.append("workflow.adr_dir contains unsupported characters")
    if not isinstance(workflow.get("human_gates"), bool):
        errors.append("workflow.human_gates must be a boolean")
    if not isinstance(workflow.get("use_serve"), bool):
        errors.append("workflow.use_serve must be a boolean")
    if errors:
        raise InstallError("invalid config.yml:\n  " + "\n  ".join(errors))
    return cfg


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
    example = deps.yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8")) or {}
    new = collect_keys(example) - collect_keys(cfg)
    if new:
        print(f"new options available (not yet set in {config_path}):")
        for key in sorted(new):
            print(f"  {key}")
