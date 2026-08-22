"""Configuration: defaults, config.yml loading, merging and validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from . import InstallError

DEFAULT_STATE_DIR = ".workflow"
DEFAULT_MAX_FIX_ITERATIONS = 5
DEFAULT_MAX_SRP_ITERATIONS = 5
DEFAULT_MAX_BUG_ITERATIONS = 5
DEFAULT_MAX_COMMENT_ITERATIONS = 5
DEFAULT_MAX_IMPLEMENT_ITERATIONS = 2
DEFAULT_MAX_QUESTIONS_ITERATIONS = 3
DEFAULT_SHELL_TIMEOUT = 7200
DEFAULT_REASONING = "max"
DEFAULT_ADR_DIR = "architecture"
DEFAULT_BACKEND = "opencode"
BACKENDS = ("opencode", "cursor")

DEFAULT_CONFIG: dict[str, Any] = {
    "backend": DEFAULT_BACKEND,
    "workflow": {
        "state_dir": DEFAULT_STATE_DIR,
        "max_fix_iterations": DEFAULT_MAX_FIX_ITERATIONS,
        "max_srp_iterations": DEFAULT_MAX_SRP_ITERATIONS,
        "max_bug_iterations": DEFAULT_MAX_BUG_ITERATIONS,
        "max_comment_iterations": DEFAULT_MAX_COMMENT_ITERATIONS,
        "max_implement_iterations": DEFAULT_MAX_IMPLEMENT_ITERATIONS,
        "max_questions_iterations": DEFAULT_MAX_QUESTIONS_ITERATIONS,
        "shell_timeout": DEFAULT_SHELL_TIMEOUT,
        "adr_dir": DEFAULT_ADR_DIR,
        "human_gates": True,
        "use_serve": False,
    },
}


def load_config(path: str | Path) -> dict[str, Any]:
    # Config loading is the one place a YAML parse error can surface from user
    # input, so it is converted to InstallError here — main() then stays flat
    # without special-casing yaml types. A root that is valid YAML but not a
    # mapping (a bare scalar or a list) is the same class of user error, and
    # dict(raw) would otherwise raise an unhandled TypeError instead.
    # PyYAML is a declared wheel dependency (pyproject.toml `dependencies`),
    # so the import is unconditional.
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise InstallError(f"invalid config.yml: {exc}") from exc
    if not isinstance(raw, dict):
        raise InstallError("invalid config.yml: top-level must be a mapping")
    return dict(raw)


def opencode_models_complete(cfg: dict[str, Any]) -> bool:
    """Whether the opencode section carries usable models for both roles.

    The single predicate under which render.render_agents() writes the
    opencode agent files; verify.check_files() requires those files under
    the same condition, so a config whose opencode section is empty or
    incomplete (valid when another backend is active) neither renders nor
    demands the agent files.
    """
    models = (cfg.get("opencode") or {}).get("models") or {}
    planner = models.get("planner") or {}
    executor = models.get("executor") or {}
    return bool(
        planner.get("provider")
        and planner.get("model")
        and executor.get("provider")
        and executor.get("model")
    )


def apply_defaults(raw: Any) -> dict[str, Any]:
    # Same guard as load_config: raw may be None (treated as empty config) but
    # any other non-mapping top level is a user error, not a TypeError.
    if raw is not None and not isinstance(raw, dict):
        raise InstallError("invalid config.yml: top-level must be a mapping")
    cfg = dict(raw or {})
    # Legacy top-level `models:` is folded into `opencode.models` so existing
    # configs keep working; an explicit opencode section wins over the legacy
    # key (the user is mid-migration and opencode is the section they wrote).
    if "models" in cfg:
        if "opencode" not in cfg:
            cfg["opencode"] = {"models": cfg["models"]}
        del cfg["models"]
    cfg.setdefault("backend", DEFAULT_BACKEND)
    workflow = cfg.get("workflow") or {}
    if not isinstance(workflow, dict):
        raise InstallError("invalid config.yml: workflow must be a mapping")
    merged_workflow = dict(DEFAULT_CONFIG["workflow"])
    merged_workflow.update(workflow)
    cfg["workflow"] = merged_workflow
    if "opencode" in cfg:
        opencode = cfg["opencode"]
        if not isinstance(opencode, dict):
            raise InstallError("invalid config.yml: opencode must be a mapping")
        models = opencode.get("models") or {}
        if not isinstance(models, dict):
            raise InstallError("invalid config.yml: opencode.models must be a mapping")
        for role in ("planner", "executor"):
            model = models.get(role) or {}
            if not isinstance(model, dict):
                raise InstallError(f"invalid config.yml: opencode.models.{role} must be a mapping")
            model = dict(model)
            model.setdefault("reasoning", DEFAULT_REASONING)
            models[role] = model
        opencode["models"] = models
        cfg["opencode"] = opencode
    if "cursor" in cfg:
        cursor = cfg["cursor"]
        if not isinstance(cursor, dict):
            raise InstallError("invalid config.yml: cursor must be a mapping")
        models = cursor.get("models") or {}
        if not isinstance(models, dict):
            raise InstallError("invalid config.yml: cursor.models must be a mapping")
        for role in ("planner", "executor"):
            model = models.get(role) or {}
            if not isinstance(model, dict):
                raise InstallError(f"invalid config.yml: cursor.models.{role} must be a mapping")
            models[role] = model
        cursor["models"] = models
        cfg["cursor"] = cursor
    return cfg


def validate_config(cfg: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    backend = cfg.get("backend")
    if backend not in BACKENDS:
        errors.append(f"backend must be one of: opencode, cursor (got {backend!r})")
    # Only the active backend's models are strictly required (symmetric to
    # the opencode provider/model/reasoning fields); the inactive section, if
    # present, was already validated structurally by apply_defaults.
    if backend == "opencode":
        models = (cfg.get("opencode") or {}).get("models") or {}
        for role in ("planner", "executor"):
            model = models.get(role) or {}
            for key in ("provider", "model", "reasoning"):
                value = model.get(key)
                if not value:
                    errors.append(f"missing required key: opencode.models.{role}.{key}")
                elif "<" in str(value) or ">" in str(value):
                    errors.append(
                        f"placeholder value in opencode.models.{role}.{key} - edit config.yml first"
                    )
    elif backend == "cursor":
        models = (cfg.get("cursor") or {}).get("models") or {}
        for role in ("planner", "executor"):
            model = models.get(role) or {}
            value = model.get("model")
            if not value:
                errors.append(f"missing required key: cursor.models.{role}.model")
            elif "<" in str(value) or ">" in str(value):
                errors.append(
                    f"placeholder value in cursor.models.{role}.model - edit config.yml first"
                )
    workflow = cfg["workflow"]
    for key in (
        "max_fix_iterations",
        "max_srp_iterations",
        "max_bug_iterations",
        "max_comment_iterations",
        "max_implement_iterations",
        "max_questions_iterations",
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
