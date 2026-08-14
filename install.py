#!/usr/bin/env python3
"""Install the spec-kit-llm-client planner/executor pipeline.

Usage:
  python3 install.py [--update] [--uninstall] [--register] [--home DIR] [--yes]

Installs global opencode agents (planner, executor), a run-agent.sh session
glue script, and a spec-kit workflow (adr-pipeline) under
~/.config/spec-kit-llm-client/. See README.md for usage.

Options:
  --update       reinstall templates and print newly available config options
  --uninstall    remove installed files (keeps your config.yml)
  --register     install the workflow by ID into the current Spec Kit project
  --home DIR     base directory instead of the real home (used by tests)
  --yes          answer yes to all prompts
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from string import Template

try:
    import yaml
except ImportError:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = REPO_ROOT / "templates"
CONFIG_EXAMPLE = REPO_ROOT / "config.example.yml"

MIN_SPECIFY_VERSION = (0, 16)
DEFAULT_STATE_DIR = ".workflow"
DEFAULT_MAX_FIX_ITERATIONS = 5
DEFAULT_SHELL_TIMEOUT = 7200
DEFAULT_REASONING = "max"
DEFAULT_ADR_DIR = "architecture"


class InstallError(Exception):
    pass


def find_in_path(name):
    return shutil.which(name)


def run(cmd, cwd=None, env=None, check=True):
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise InstallError(
            "command failed with exit code %d: %s\n%s"
            % (result.returncode, " ".join(cmd), result.stderr.strip())
        )
    return result


def network_available():
    try:
        socket.create_connection(("pypi.org", 443), timeout=5).close()
        return True
    except OSError:
        return False


def parse_specify_version(text):
    m = re.search(r"(\d+)\.(\d+)", text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _specify_candidates():
    exe = "specify.exe" if os.name == "nt" else "specify"
    candidates = []
    for base in (
        Path.home() / ".local" / "bin",
        Path.home() / ".local" / "share" / "uv" / "tools" / "specify-cli" / "bin",
    ):
        candidate = base / exe
        if candidate.exists():
            candidates.append(str(candidate))
    return candidates


def get_specify_version():
    path = find_in_path("specify")
    if not path:
        return None
    result = run([path, "--version"], check=False)
    if result.returncode != 0:
        return None
    return parse_specify_version(result.stdout)


def latest_specify_version():
    for path in _specify_candidates() + [find_in_path("specify")]:
        if not path:
            continue
        result = run([path, "--version"], check=False)
        if result.returncode != 0:
            continue
        version = parse_specify_version(result.stdout)
        if version:
            return version, path
    return None, None


def _in_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _pip_works(python):
    result = run([python, "-m", "pip", "--version"], check=False)
    return result.returncode == 0


def ensure_pyyaml():
    global yaml
    if yaml is not None:
        return
    if not network_available():
        raise InstallError(
            "no network access and PyYAML is not installed; "
            "run: pip3 install --user pyyaml"
        )
    candidates = []
    python = find_in_path("python3")
    uv = find_in_path("uv")
    if _in_venv():
        if uv:
            candidates.append([uv, "pip", "install", "pyyaml"])
        if python and _pip_works(python):
            candidates.append([python, "-m", "pip", "install", "pyyaml"])
    pip3 = find_in_path("pip3")
    if pip3:
        candidates.append([pip3, "install", "--user", "pyyaml"])
    if uv and not _in_venv():
        candidates.append([uv, "pip", "install", "--system", "pyyaml"])
    if python and not _in_venv() and _pip_works(python):
        candidates.append([python, "-m", "pip", "install", "--user", "pyyaml"])
    for cmd in candidates:
        result = run(cmd, check=False)
        if result.returncode != 0:
            continue
        try:
            import importlib

            yaml = importlib.import_module("yaml")
            return
        except ImportError:
            continue
    raise InstallError(
        "could not install PyYAML; install it manually: pip3 install --user pyyaml"
    )


def ensure_specify():
    version = get_specify_version()
    if version and version >= MIN_SPECIFY_VERSION:
        return
    if not network_available():
        raise InstallError(
            "no network access and specify-cli is not installed; "
            "run: uv tool install specify-cli"
        )
    for tool in ("uv", "pipx", "pip3"):
        path = find_in_path(tool)
        if not path:
            continue
        if tool == "uv":
            result = run([path, "tool", "install", "specify-cli"], check=False)
        elif tool == "pipx":
            result = run([path, "install", "specify-cli"], check=False)
        else:
            result = run([path, "install", "--user", "specify-cli"], check=False)
        if result.returncode != 0:
            continue
        if get_specify_version():
            return
        version, binary = latest_specify_version()
        if version and version >= MIN_SPECIFY_VERSION:
            print(
                "warning: specify-cli installed at %s but not on PATH; "
                "add it to PATH (e.g. ~/.local/bin)" % binary
            )
            return
    python = find_in_path("python3")
    if python and _pip_works(python):
        result = run([python, "-m", "pip", "install", "--user", "specify-cli"], check=False)
        if result.returncode == 0:
            if get_specify_version():
                return
            version, binary = latest_specify_version()
            if version and version >= MIN_SPECIFY_VERSION:
                print(
                    "warning: specify-cli installed at %s but not on PATH; "
                    "add it to PATH (e.g. ~/.local/bin)" % binary
                )
                return
    raise InstallError(
        "could not install specify-cli; install uv "
        "(https://docs.astral.sh/uv/) and rerun"
    )


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


def ensure_config(paths):
    shutil.copy2(CONFIG_EXAMPLE, paths["config_example"])
    if not paths["config"].exists():
        shutil.copy2(CONFIG_EXAMPLE, paths["config"])
        print("created %s with defaults (edit it to change models)" % paths["config"])


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
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


def render_file(template_path, target_path, mapping):
    text = Template(template_path.read_text(encoding="utf-8")).substitute(mapping)
    target_path.write_text(text, encoding="utf-8")


def render_agents(cfg, paths):
    planner = cfg["models"]["planner"]
    executor = cfg["models"]["executor"]
    render_file(
        TEMPLATES_DIR / "planner.md.tpl",
        paths["agents"] / "planner.md",
        {
            "planner_provider": planner["provider"],
            "planner_model": planner["model"],
            "planner_reasoning": planner["reasoning"],
        },
    )
    render_file(
        TEMPLATES_DIR / "executor.md.tpl",
        paths["agents"] / "executor.md",
        {
            "executor_provider": executor["provider"],
            "executor_model": executor["model"],
            "executor_reasoning": executor["reasoning"],
        },
    )


def render_run_agent(cfg, paths):
    use_serve = cfg["workflow"]["use_serve"]
    serve_attach = "--attach http://localhost:4096" if use_serve else ""
    render_file(
        TEMPLATES_DIR / "run-agent.sh.tpl",
        paths["run_agent"],
        {"serve_attach": serve_attach},
    )
    paths["run_agent"].chmod(0o755)


def render_workflow(cfg, paths):
    workflow = cfg["workflow"]
    if workflow["human_gates"]:
        verdict_decl = ""
        approve_verdict = ""
    else:
        verdict_decl = (
            "  adr_verdict:\n"
            '    type: string\n'
            '    enum: ["", approve, revise, reject]\n'
            '    default: "approve"'
        )
        approve_verdict = "    verdict_input: adr_verdict"
    render_file(
        TEMPLATES_DIR / "adr-pipeline.yml.tpl",
        paths["workflow"],
        {
            "run_agent": str(paths["run_agent"]),
            "state_dir": workflow["state_dir"],
            "adr_dir": workflow["adr_dir"],
            "step_timeout": str(workflow["shell_timeout"]),
            "verdict_inputs_decl": verdict_decl,
            "approve_adr_verdict": approve_verdict,
            "max_fix_iterations": str(workflow["max_fix_iterations"]),
        },
    )


def validate_install(paths):
    for name in ("planner.md", "executor.md"):
        agent = paths["agents"] / name
        if not agent.exists():
            raise InstallError("generated agent missing: %s" % agent)
    if not os.access(paths["run_agent"], os.X_OK):
        raise InstallError("run-agent.sh is not executable: %s" % paths["run_agent"])

    with tempfile.TemporaryDirectory() as tmp:
        result = run(
            ["specify", "workflow", "run", str(paths["workflow"]), "--json"],
            cwd=tmp,
            check=False,
        )
        combined = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
        if result.returncode == 0 or "required input" not in combined:
            raise InstallError(
                "workflow syntax check failed:\n%s"
                % ((result.stderr or result.stdout).strip())
            )

    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(paths["agents"].parent.parent)
    result = run(["opencode", "agent", "list"], check=False, env=env)
    if result.returncode != 0:
        raise InstallError("opencode agent list failed: %s" % result.stderr.strip())
    names = set(
        re.findall(r"^(\S+)\s+\((?:primary|subagent)\)", result.stdout, re.M)
    )
    for name in ("planner", "executor"):
        if name not in names:
            raise InstallError(
                "opencode does not see the '%s' agent; check %s"
                % (name, paths["agents"])
            )


def print_instructions(paths):
    print(
        "\nDone. Next steps:\n"
        "  1. Edit %s to choose your models "
        "(planner = strong, executor = cheap), then rerun install.py.\n"
        "  2. In any project run:\n"
        "       specify workflow run %s -i feature=\"your feature description\"\n"
        "     or, from a Spec Kit project (run 'specify init' first), install by ID once:\n"
        "       python3 %s --register\n"
        "     and then:\n"
        "       specify workflow run adr-pipeline -i feature=\"...\"\n"
        "  3. If the run pauses at a gate, review and resume with:\n"
        "       specify workflow resume <run_id>\n"
        % (paths["config"], paths["workflow"], REPO_ROOT / "install.py")
    )


def do_register(paths):
    if not paths["workflow"].exists():
        raise InstallError("adr-pipeline.yml not found - run install.py first")
    specify = find_in_path("specify")
    if not specify:
        raise InstallError("'specify' not found on PATH - run install.py first")
    if not Path(".specify").exists():
        raise InstallError(
            "not a Spec Kit project (no .specify/ directory); run 'specify init' first"
        )
    run([specify, "workflow", "add", str(paths["workflow"]), "--dev"])
    print("installed 'adr-pipeline' into this project")
    print("run it with: specify workflow run adr-pipeline -i feature=\"...\"")


def confirm(prompt):
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _uninstall_pip_package(package):
    attempts = []
    python = find_in_path("python3")
    if python and _pip_works(python):
        attempts.append([python, "-m", "pip", "uninstall", "-y", package])
    pip3 = find_in_path("pip3")
    if pip3:
        attempts.append([pip3, "uninstall", "-y", package])
        attempts.append([pip3, "uninstall", "-y", "--user", package])
    for cmd in attempts:
        result = run(cmd, check=False)
        if result.returncode == 0:
            return True
    return False


def do_uninstall(paths, yes):
    removed = []
    for path in (
        paths["agents"] / "planner.md",
        paths["agents"] / "executor.md",
        paths["run_agent"],
        paths["workflow"],
        paths["config_example"],
    ):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    if removed:
        print("removed:\n  " + "\n  ".join(removed))
    for directory in (paths["agents"], paths["scripts"], paths["sklc"]):
        try:
            directory.rmdir()
        except OSError:
            pass
    print("kept your configuration: %s" % paths["config"])
    if yes or confirm("uninstall specify-cli? [y/N] "):
        uv = find_in_path("uv")
        if uv and get_specify_version():
            run([uv, "tool", "uninstall", "specify-cli"], check=False)
    if yes or confirm("uninstall PyYAML? [y/N] "):
        _uninstall_pip_package("pyyaml")


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
    example = yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8")) or {}
    new = collect_keys(example) - collect_keys(cfg)
    if new:
        print("new options available (not yet set in %s):" % config_path)
        for key in sorted(new):
            print("  %s" % key)


def run_install(args):
    home = Path(args.home).expanduser() if args.home else Path.home()
    paths = build_paths(home)
    if args.register:
        if args.home:
            raise InstallError("--register cannot be combined with --home")
        if args.uninstall or args.update:
            raise InstallError(
                "--register cannot be combined with --uninstall/--update"
            )
        do_register(paths)
        return
    if args.uninstall and args.update:
        raise InstallError("--uninstall cannot be combined with --update")
    if args.uninstall:
        do_uninstall(paths, args.yes)
        return

    print("spec-kit-llm-client installer")
    if not find_in_path("python3"):
        raise InstallError("python3 not found in PATH")
    if not find_in_path("opencode"):
        raise InstallError(
            "opencode not found in PATH - install it first (https://opencode.ai/docs)"
        )
    ensure_pyyaml()
    ensure_specify()
    for directory in (paths["agents"], paths["scripts"], paths["sklc"]):
        directory.mkdir(parents=True, exist_ok=True)
    ensure_config(paths)
    cfg = validate_config(load_config(paths["config"]))
    if args.update:
        print_diff_new_options(paths["config"], cfg)
    render_agents(cfg, paths)
    render_run_agent(cfg, paths)
    render_workflow(cfg, paths)
    validate_install(paths)
    print("installation verified")
    print_instructions(paths)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Install the spec-kit-llm-client planner/executor pipeline"
    )
    parser.add_argument(
        "--update", action="store_true",
        help="reinstall templates and print newly available config options",
    )
    parser.add_argument(
        "--uninstall", action="store_true", help="remove installed files"
    )
    parser.add_argument(
        "--register", action="store_true",
        help="install the workflow by ID into the current Spec Kit project",
    )
    parser.add_argument(
        "--home", metavar="DIR",
        help="base directory instead of the real home (used by tests)",
    )
    parser.add_argument(
        "--yes", action="store_true", help="answer yes to all prompts"
    )
    return parser.parse_args(argv)


def main(argv=None):
    try:
        run_install(parse_args(argv))
    except InstallError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except Exception as exc:
        if yaml is not None and isinstance(exc, yaml.YAMLError):
            print("error: %s" % exc, file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
