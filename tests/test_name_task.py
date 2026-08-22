"""Behavioral tests for name-task.sh backend dispatch.

The one-shot slug generator runs the executor once per call; these tests run
it with fake `cursor-agent`/`opencode` binaries on PATH, asserting the
invocation and the returned slug for both backends.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NAME_TASK = REPO_ROOT / "src/modus_operandi/data/pipeline_scripts" / "name-task.sh"

CURSOR_AGENT_SCRIPT = """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$FAKE_CURSOR_LOG"
printf '  kanban-board  \\n'
"""

OPENCODE_SCRIPT = """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$FAKE_OPENCODE_LOG"
printf '%s\\n' '{"type":"text","part":{"type":"text","text":"thinking about it"}}'
printf '%s\\n' '{"type":"text","part":{"type":"text","text":"kanban-board"}}'
"""


def _safe_system_path() -> str:
    # The fakes must shadow any REAL cursor-agent/agent binaries on the host
    # PATH (this machine has both installed): drop the directories that carry
    # them, keep the rest for python3/sh. The opencode binary is left alone:
    # the opencode branch invokes `opencode` by name and the self.bin fake
    # comes first on PATH, so it already shadows the real one.
    entries = []
    for entry in os.environ["PATH"].split(os.pathsep):
        directory = Path(entry)
        if any((directory / name).exists() for name in ("cursor-agent", "agent")):
            continue
        entries.append(entry)
    return os.pathsep.join(entries)


class NameTaskTest(unittest.TestCase):
    """End-to-end backend dispatch of the installed name-task.sh."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="name_task_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.name_task = self.tmp / "name-task.sh"
        shutil.copy2(NAME_TASK, self.name_task)
        self.name_task.chmod(0o755)
        self.cursor_log = self.tmp / "cursor.log"
        self.opencode_log = self.tmp / "opencode.log"

    def _env(self, **extra: str) -> dict[str, str]:
        env = {
            "PATH": str(self.bin) + os.pathsep + _safe_system_path(),
            "MO_EXECUTOR_MODEL": "executor-slug",
            "FAKE_CURSOR_LOG": str(self.cursor_log),
            "FAKE_OPENCODE_LOG": str(self.opencode_log),
        }
        env.update(extra)
        return env

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _run(self, feature: str, **env_extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.name_task), feature],
            capture_output=True,
            text=True,
            cwd=str(self.tmp),
            env=self._env(**env_extra),
        )

    def _args(self, log_path: Path) -> list[str]:
        return [a.decode() for a in log_path.read_bytes().split(b"\0") if a]

    def test_cursor_uses_text_output_and_returns_trimmed_slug(self) -> None:
        self._write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        result = self._run("build a kanban board", MO_BACKEND="cursor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "kanban-board")
        args = self._args(self.cursor_log)
        self.assertEqual(
            args[:6], ["-p", "--output-format", "text", "--force", "--trust", "--model"]
        )
        self.assertEqual(args[6], "executor-slug")
        self.assertTrue(args[-1].startswith("Reply with ONLY a short kebab-case slug"))

    def test_cursor_missing_binary_errors(self) -> None:
        result = self._run("build a kanban board", MO_BACKEND="cursor")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not found in PATH", result.stderr)

    def test_cursor_missing_model_errors(self) -> None:
        self._write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        result = self._run("build a kanban board", MO_BACKEND="cursor", MO_EXECUTOR_MODEL="")
        self.assertEqual(result.returncode, 2)
        self.assertIn("MO_EXECUTOR_MODEL", result.stderr)

    def test_opencode_default_uses_json_stream(self) -> None:
        self._write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        result = self._run("build a kanban board")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "kanban-board")
        args = self._args(self.opencode_log)
        self.assertEqual(args[:5], ["run", "--agent", "executor", "--auto", "--format"])
        self.assertEqual(args[5], "json")


if __name__ == "__main__":
    unittest.main()
