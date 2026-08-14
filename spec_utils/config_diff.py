"""Config diffing: options the example config offers but the user has not set."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import CONFIG_EXAMPLE, Paths, yaml_loader


def collect_keys(data: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in (data or {}).items():
        full = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            keys.update(collect_keys(value, full))
        else:
            keys.add(full)
    return keys


def diff_new_options(example_path: str | Path, raw_cfg: dict[str, Any]) -> set[str]:
    """Keys present in the example config but not set in the user's raw config.

    raw_cfg must be the user's config as loaded, before apply_defaults():
    defaults fill every key, so a diff against the defaults-filled config
    would always be empty.
    """
    example = yaml_loader.yaml.safe_load(Path(example_path).read_text(encoding="utf-8")) or {}
    return collect_keys(example) - collect_keys(raw_cfg)


def report_new_options(paths: Paths, raw_cfg: dict[str, Any]) -> None:
    """Print the config keys the example offers but the user has not set.

    raw_cfg must be the user's config as loaded, before apply_defaults()
    (same contract as diff_new_options).
    """
    new = diff_new_options(CONFIG_EXAMPLE, raw_cfg)
    if new:
        print(f"new options available (not yet set in {paths['config']}):")
        for key in sorted(new):
            print(f"  {key}")
