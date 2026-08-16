"""Shared fixtures for the run-pipeline.py tests.

run_pipeline.py is split into modules (one class per file, plus the shared
helpers in _run_pipeline_common.py). The tests copy the whole module set
into a temp dir and load the entry as a module, so the __file__-derived
paths (SOUND_FILE, CONFIG_PATH) are isolated per test and both the runtime
config handling and the wrapper behavior are exercised.
"""

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = REPO_ROOT / "pipeline_scripts"

# The modules that make up the run-pipeline wrapper: the entry plus the
# one-class-per-file modules, the shared helpers module and the
# one-concern-per-file modules.
_MODULES = (
    "run_pipeline",
    "_run_pipeline_common",
    "run_id_discoverer",
    "step_result_poller",
    "agent_log_tailer",
    "gate_state",
    "buffered_emitter",
    "live_monitor",
    "config_invocation",
    "run_statistics",
    "latency_table",
    # latency_table imports KIND_ORDER from check_review.py (single source of
    # truth for the review order), which itself imports task_utils.py.
    "check_review",
    "task_utils",
    "notify",
    "feedback_editor",
    "pty_spawn",
    "editor",
)

# Submodules exposed on the loaded entry module so tests can patch their
# attributes (e.g. mod._run_pipeline_common.stamp) without re-importing.
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

    def __init__(self, lines, returncode=0, **kwargs):
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode


def load_run_pipeline() -> types.ModuleType:
    tmpdir = Path(tempfile.mkdtemp(prefix="run_pipeline_test_"))
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
        # re-exports e.g. the `notify` function, which must not be shadowed
        # by the `notify` submodule when tests patch mod.notify.
        if not hasattr(module, name):
            setattr(module, name, sys.modules[name])
    return module


def point_config_at(mod: types.ModuleType, tmp: str, **workflow_overrides) -> Path:
    """Write a config.yml into tmp and point the module's CONFIG_PATH at it.

    Returns the config path. main() reads the installed config through
    mod.CONFIG_PATH, so every main()-driven test controls it this way.
    """
    import yaml

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["workflow"].update(workflow_overrides)
    path = Path(tmp) / "config.yml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    mod.CONFIG_PATH = path
    return path
