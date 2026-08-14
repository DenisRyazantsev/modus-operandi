"""Configuration: defaults, config.yml loading, merging and validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import InstallError, yaml_loader

DEFAULT_STATE_DIR = ".workflow"
DEFAULT_MAX_FIX_ITERATIONS = 5
DEFAULT_MAX_SRP_ITERATIONS = 5
DEFAULT_MAX_BUG_ITERATIONS = 5
DEFAULT_MAX_COMMENT_ITERATIONS = 5
DEFAULT_MAX_ADR_ITERATIONS = 3
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
        "max_adr_iterations": DEFAULT_MAX_ADR_ITERATIONS,
        "shell_timeout": DEFAULT_SHELL_TIMEOUT,
        "adr_dir": DEFAULT_ADR_DIR,
        "human_gates": True,
        "use_serve": False,
    }
}


def load_config(path: str | Path) -> dict[str, Any]:
    # Config loading is the one place a YAML parse error can surface from user
    # input, so it is converted to InstallError here — main() then stays flat
    # without special-casing yaml types. A root that is valid YAML but not a
    # mapping (a bare scalar or a list) is the same class of user error, and
    # dict(raw) would otherwise raise an unhandled TypeError instead.
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        raw = yaml_loader.yaml.safe_load(text) or {}
    except Exception as exc:
        if yaml_loader.yaml is not None and isinstance(exc, yaml_loader.yaml.YAMLError):
            raise InstallError(f"invalid config.yml: {exc}") from exc
        raise
    if not isinstance(raw, dict):
        raise InstallError("invalid config.yml: top-level must be a mapping")
    return dict(raw)


def apply_defaults(raw: Any) -> dict[str, Any]:
    # Same guard as load_config: raw may be None (treated as empty config) but
    # any other non-mapping top level is a user error, not a TypeError.
    if raw is not None and not isinstance(raw, dict):
        raise InstallError("invalid config.yml: top-level must be a mapping")
    cfg = dict(raw or {})
    workflow = cfg.get("workflow") or {}
    if not isinstance(workflow, dict):
        raise InstallError("invalid config.yml: workflow must be a mapping")
    merged_workflow = dict(DEFAULT_CONFIG["workflow"])
    merged_workflow.update(workflow)
    cfg["workflow"] = merged_workflow
    models = cfg.get("models") or {}
    if not isinstance(models, dict):
        raise InstallError("invalid config.yml: models must be a mapping")
    cfg["models"] = models
    for role in ("planner", "executor"):
        model = models.get(role) or {}
        if not isinstance(model, dict):
            raise InstallError(f"invalid config.yml: models.{role} must be a mapping")
        model = dict(model)
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
                errors.append(f"placeholder value in models.{role}.{key} - edit config.yml first")
    workflow = cfg["workflow"]
    for key in (
        "max_fix_iterations",
        "max_srp_iterations",
        "max_bug_iterations",
        "max_comment_iterations",
        "max_adr_iterations",
    ):
        value = workflow.get(key)
        # type() is int, not isinstance: bool is a subclass of int, so
        # `max_fix_iterations: true` must not pass the integer check — it
        # would render as "True" into the generated workflows.
        if type(value) is not int or value < 1:
            errors.append(f"workflow.{key} must be an integer >= 1")
    value = workflow.get("shell_timeout")
    if type(value) is not int or value < 1:
        errors.append("workflow.shell_timeout must be a positive number of seconds")
    for key in ("state_dir", "adr_dir"):
        value = workflow.get(key, "")
        # The regex below is only meaningful for strings: str(None) is "None"
        # and would pass it, silently pointing the workflow at "None/..." dirs.
        if not isinstance(value, str):
            errors.append(f"workflow.{key} must be a string")
        elif not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
            errors.append(f"workflow.{key} contains unsupported characters")
    if not isinstance(workflow.get("human_gates"), bool):
        errors.append("workflow.human_gates must be a boolean")
    if not isinstance(workflow.get("use_serve"), bool):
        errors.append("workflow.use_serve must be a boolean")
    if errors:
        raise InstallError("invalid config.yml:\n  " + "\n  ".join(errors))
    return cfg
