"""Configuration: paths, defaults, config.yml loading and validation."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import CONFIG_EXAMPLE, InstallError
from . import deps

DEFAULT_STATE_DIR = ".workflow"
DEFAULT_MAX_FIX_ITERATIONS = 5
DEFAULT_SHELL_TIMEOUT = 7200
DEFAULT_REASONING = "max"
DEFAULT_ADR_DIR = "architecture"

DEFAULT_CONFIG = {
    "workflow": {
        "state_dir": DEFAULT_STATE_DIR,
        "max_fix_iterations": DEFAULT_MAX_FIX_ITERATIONS,
        "shell_timeout": DEFAULT_SHELL_TIMEOUT,
        "adr_dir": DEFAULT_ADR_DIR,
        "human_gates": True,
        "use_serve": False,
    }
}


def build_paths(home):
    base = Path(home)
    return {
        "agents": base / ".config" / "opencode" / "agent",
        "scripts": base / ".config" / "opencode" / "scripts",
        "sklc": base / ".config" / "spec-kit-llm-client",
        "config": base / ".config" / "spec-kit-llm-client" / "config.yml",
        "config_example": base / ".config" / "spec-kit-llm-client" / "config.example.yml",
        "workflow": base / ".config" / "spec-kit-llm-client" / "adr-pipeline.yml",
        "run_agent": base / ".config" / "opencode" / "scripts" / "run-agent.sh",
    }


def ensure_config(paths):
    shutil.copy2(CONFIG_EXAMPLE, paths["config_example"])
    if not paths["config"].exists():
        shutil.copy2(CONFIG_EXAMPLE, paths["config"])
        print("created %s with defaults (edit it to change models)" % paths["config"])


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        cfg = deps.yaml.safe_load(fh) or {}
    workflow = dict(DEFAULT_CONFIG["workflow"])
    workflow.update(cfg.get("workflow") or {})
    cfg["workflow"] = workflow
    cfg["models"] = cfg.get("models") or {}
    for role in ("planner", "executor"):
        model = dict(cfg["models"].get(role) or {})
        model.setdefault("reasoning", DEFAULT_REASONING)
        cfg["models"][role] = model
    return cfg


def validate_config(cfg):
    errors = []
    for role in ("planner", "executor"):
        model = cfg["models"].get(role) or {}
        for key in ("provider", "model", "reasoning"):
            value = model.get(key)
            if not value:
                errors.append("missing required key: models.%s.%s" % (role, key))
            elif "<" in str(value) or ">" in str(value):
                errors.append(
                    "placeholder value in models.%s.%s - edit config.yml first"
                    % (role, key)
                )
    workflow = cfg["workflow"]
    if not isinstance(workflow.get("max_fix_iterations"), int) or workflow["max_fix_iterations"] < 1:
        errors.append("workflow.max_fix_iterations must be an integer >= 1")
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


def collect_keys(data, prefix=""):
    keys = set()
    for key, value in (data or {}).items():
        full = "%s.%s" % (prefix, key) if prefix else str(key)
        if isinstance(value, dict):
            keys.update(collect_keys(value, full))
        else:
            keys.add(full)
    return keys


def print_diff_new_options(config_path, cfg):
    example = deps.yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8")) or {}
    new = collect_keys(example) - collect_keys(cfg)
    if new:
        print("new options available (not yet set in %s):" % config_path)
        for key in sorted(new):
            print("  %s" % key)
