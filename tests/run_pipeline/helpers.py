"""Shared fixtures for the run-pipeline.py tests.

run_pipeline.py is split into modules (one class per file, plus the
one-concern-per-file helpers: engine_output, feedback_gate, display,
run_state, workflow_info). The tests copy the whole module set
into a temp dir and load the entry as a module, so the __file__-derived
paths (SOUND_FILE, CONFIG_PATH) are isolated per test and both the runtime
config handling and the wrapper behavior are exercised.
"""

import importlib.util
import json
import sys
import tempfile
import types
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = REPO_ROOT / "src/modus_operandi/data/pipeline_scripts"

# The modules that make up the run-pipeline wrapper: the entry plus the
# one-class-per-file modules and the one-concern-per-file helper modules.
_MODULES = (
    "run_pipeline",
    "engine_output",
    "feedback_gate",
    "display",
    "run_state",
    "workflow_info",
    "run_id_discoverer",
    "step_result_poller",
    "agent_log_tailer",
    "gate_state",
    "buffered_emitter",
    "live_monitor",
    "live_lines",
    "table_format",
    "usage_parser",
    "config_invocation",
    "run_statistics",
    "latency_table",
    # latency_table imports KIND_ORDER from check_review.py (single source of
    # truth for the review order), which itself imports task_utils.py.
    "check_review",
    "task_utils",
    "validate_inputs",
    "notify",
    "feedback_editor",
    "pty_spawn",
    "wrapper_cli",
    "stdout_reader",
    "run_finish",
    "editor",
)

# Submodules exposed on the loaded entry module so tests can patch their
# attributes (e.g. mod.display.stamp) without re-importing.
_SUBMODULE_NAMES = _MODULES[1:]

DEFAULT_CONFIG = {
    "workflow": {
        "state_dir": ".workflow",
        "adr_dir": "architecture",
        "human_gates": True,
        "use_serve": False,
    }
}


class FakeProc:
    """Stands in for a subprocess.Popen handle in main()-driven tests."""

    def __init__(self, lines: Iterable[str], returncode: int = 0, **kwargs: object) -> None:
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode


def load_run_pipeline() -> types.ModuleType:
    base = Path(tempfile.mkdtemp(prefix="run_pipeline_test_"))
    # The modules are copied into a NESTED subdir: the wrapper derives its
    # installed config dir from __file__ (../../.. + config name), and with
    # the copy nested three levels deep that dir lands inside the temp base
    # where tests can write real workflow files for it.
    tmpdir = base / "modules" / "deep"
    tmpdir.mkdir(parents=True)
    for name in _MODULES:
        (tmpdir / f"{name}.py").write_bytes((_SRC_DIR / f"{name}.py").read_bytes())
    sys.path.insert(0, str(tmpdir))
    # Force the submodules to be freshly imported from THIS tempdir: a stale
    # sys.modules entry from a previous test would point at another copy.
    for name in _MODULES:
        sys.modules.pop(name, None)
    path = tmpdir / "run_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_pipeline_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_pipeline_under_test"] = module
    spec.loader.exec_module(module)
    for name in _SUBMODULE_NAMES:
        # Skip names the entry module already defines: the wrapper
        # re-exports e.g. the `play_signal` function from notify.py, which
        # must not be shadowed by the `notify` submodule when tests patch
        # mod.play_signal.
        if not hasattr(module, name):
            if name not in sys.modules:
                # Standalone scripts the entry module never imports (e.g.
                # validate_inputs.py, invoked by the workflow as a script):
                # import them explicitly so tests can reach them through
                # the entry module.
                importlib.import_module(name)
            setattr(module, name, sys.modules[name])
    return module


def point_config_at(
    mod: types.ModuleType,
    tmp: str,
    sound: dict[str, object] | None = None,
    **workflow_overrides: object,
) -> Path:
    """Write a config.yml into tmp and point the module's CONFIG_PATH at it.

    Returns the config path. main() reads the installed config through
    mod.CONFIG_PATH, so every main()-driven test controls it this way.
    """
    import yaml

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["workflow"].update(workflow_overrides)
    if sound is not None:
        cfg["sound"] = sound
    path = Path(tmp) / "config.yml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    cast(Any, mod).CONFIG_PATH = path
    return path


def export_env(
    bin_dir: Path, body: str = "#!/bin/sh\nexit 1\n", *, host: bool = True
) -> dict[str, str]:
    """PATH with a real executable `opencode` script (the export backends).

    run_statistics runs `opencode export <session_id>` through a real
    subprocess; the tests control the outcome with a real script on PATH
    (default: exit 1, i.e. the export degrades). host=False limits PATH to
    the bin dir alone, so `opencode` is genuinely not found.
    """
    import os

    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / "opencode"
    path.write_text(body)
    path.chmod(0o755)
    return {"PATH": str(bin_dir) + (f":{os.environ.get('PATH', '')}" if host else "")}
