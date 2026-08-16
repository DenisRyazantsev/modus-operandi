"""Behavioral tests for run-agent.sh backend dispatch.

run-agent.sh is a bash script, so these tests run it end-to-end with fake
`cursor-agent`/`agent`/`opencode` binaries on PATH: every fake logs its argv
to a per-binary file, so the tests assert exactly which invocation happened
(create-chat vs run, --resume, --model, role-body prefixing).
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_AGENT = REPO_ROOT / "pipeline_scripts" / "run-agent.sh"

PLANNER_BODY = "You are the planner and reviewer in a spec-driven pipeline."
EXECUTOR_BODY = "You are the executor in a spec-driven pipeline."

CURSOR_AGENT_SCRIPT = """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$FAKE_CURSOR_LOG"
if [ "$1" = "create-chat" ]; then
  printf '%s\\n' "chat-fresh-123"
  exit 0
fi
printf '%s\\n' '{"type":"result","session_id":"chat-fresh-123","result":"ok"}'
"""

CURSOR_AGENT_NO_CREATE_SCRIPT = """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$FAKE_CURSOR_LOG"
if [ "$1" = "create-chat" ]; then
  echo "create-chat unavailable" >&2
  exit 1
fi
printf '%s\\n' '{"type":"result","session_id":"chat-from-json","result":"ok"}'
"""

AGENT_SCRIPT = """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$FAKE_AGENT_LOG"
if [ "$1" = "create-chat" ]; then
  printf '%s\\n' "chat-agent-789"
  exit 0
fi
printf '%s\\n' '{"type":"result","session_id":"chat-agent-789","result":"ok"}'
"""

OPENCODE_SCRIPT = """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$FAKE_OPENCODE_LOG"
printf '%s\\n' '{"type":"init","sessionID":"sess-abc"}'
"""


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def read_invocations(log_path: Path) -> list[list[str]]:
    """Read a fake-binary log (NUL-separated argv per invocation) and group
    it into argv lists. A new invocation starts at the first arg of each
    command: `create-chat` (cursor chat mint), `-p` (cursor run) or `run`
    (opencode run). NUL separation keeps multi-line prompt args intact.
    """
    args = [a for a in log_path.read_bytes().split(b"\0") if a]
    args = [a.decode("utf-8") for a in args]
    invocations: list[list[str]] = []
    current: list[str] | None = None
    for arg in args:
        if arg in ("create-chat", "-p", "run"):
            if current is not None:
                invocations.append(current)
            current = [arg]
        elif current is not None:
            current.append(arg)
    if current is not None:
        invocations.append(current)
    return invocations


class RunAgentTest(unittest.TestCase):
    """End-to-end backend dispatch of the installed run-agent.sh."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="run_agent_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.scripts = self.tmp / "scripts"
        self.bin = self.tmp / "bin"
        self.state = self.tmp / "state"
        self.scripts.mkdir()
        self.bin.mkdir()
        self.state.mkdir()
        self.run_agent = self.scripts / "run-agent.sh"
        shutil.copy2(RUN_AGENT, self.run_agent)
        self.run_agent.chmod(0o755)
        (self.scripts / "planner-body.txt").write_text(PLANNER_BODY, encoding="utf-8")
        (self.scripts / "executor-body.txt").write_text(EXECUTOR_BODY, encoding="utf-8")
        self.cursor_log = self.tmp / "cursor.log"
        self.agent_log = self.tmp / "agent.log"
        self.opencode_log = self.tmp / "opencode.log"

    def _env(self, **extra) -> dict:
        env = {
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "SKLC_STATE_DIR": str(self.state),
            "SKLC_PLANNER_MODEL": "planner-slug",
            "SKLC_EXECUTOR_MODEL": "executor-slug",
            "FAKE_CURSOR_LOG": str(self.cursor_log),
            "FAKE_AGENT_LOG": str(self.agent_log),
            "FAKE_OPENCODE_LOG": str(self.opencode_log),
        }
        env.update(extra)
        return env

    def _run(self, *args, **env_extra) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.run_agent), *args],
            capture_output=True,
            text=True,
            cwd=str(self.tmp),
            env=self._env(**env_extra),
        )

    def _sessions(self) -> dict:
        path = self.state / "sessions.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _seed_session(self, role: str, chat_id: str) -> None:
        (self.state / "sessions.json").write_text(
            json.dumps({role: chat_id}), encoding="utf-8"
        )

    # -- cursor backend ---------------------------------------------------

    def test_cursor_first_call_mints_chat_and_prefixes_role_body(self):
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        result = self._run("planner", "write the adr now", SKLC_BACKEND="cursor")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.cursor_log)
        self.assertEqual(invs[0], ["create-chat"])
        run = invs[1]
        self.assertEqual(run[:6], ["-p", "--output-format", "json", "--force",
                                   "--trust", "--workspace"])
        self.assertEqual(run[8], "planner-slug")  # --model <role-model>
        self.assertEqual(run[9], "--resume")
        self.assertEqual(run[10], "chat-fresh-123")
        self.assertTrue(run[-1].startswith(PLANNER_BODY), "role body must prefix")
        self.assertTrue(run[-1].endswith("write the adr now"))
        self.assertEqual(self._sessions().get("planner"), "chat-fresh-123")
        self.assertIn("SESSION:chat-fresh-123", result.stdout)

    def test_cursor_resume_sends_bare_prompt_without_create_chat(self):
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        self._seed_session("planner", "chat-old-456")
        result = self._run("planner", "continue please", SKLC_BACKEND="cursor")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.cursor_log)
        self.assertEqual([i[0] for i in invs], ["-p"])  # no create-chat
        run = invs[0]
        self.assertEqual(run[9], "--resume")
        self.assertEqual(run[10], "chat-old-456")
        # Resumed chats are hot: the bare prompt, no role body.
        self.assertEqual(run[-1], "continue please")
        self.assertIn("SESSION:chat-old-456", result.stdout)

    def test_cursor_reset_mints_a_new_chat(self):
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        self._seed_session("planner", "chat-old-456")
        result = self._run("planner", "start over", "--reset", SKLC_BACKEND="cursor")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.cursor_log)
        self.assertEqual(invs[0], ["create-chat"])
        self.assertEqual(invs[1][9], "--resume")
        self.assertEqual(invs[1][10], "chat-fresh-123")
        self.assertEqual(self._sessions().get("planner"), "chat-fresh-123")

    def test_cursor_model_selected_by_role(self):
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        self._run("planner", "plan something", SKLC_BACKEND="cursor")
        self._run("executor", "implement something", SKLC_BACKEND="cursor")
        invs = read_invocations(self.cursor_log)
        planner_run = invs[1]
        executor_run = invs[3]
        self.assertEqual(planner_run[8], "planner-slug")
        self.assertEqual(executor_run[8], "executor-slug")
        self.assertTrue(executor_run[-1].startswith(EXECUTOR_BODY))

    def test_cursor_falls_back_to_agent_binary(self):
        _write_executable(self.bin / "agent", AGENT_SCRIPT)
        result = self._run("planner", "write the adr now", SKLC_BACKEND="cursor")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.agent_log)
        self.assertEqual(invs[0], ["create-chat"])
        self.assertEqual(invs[1][9], "--resume")
        self.assertEqual(invs[1][10], "chat-agent-789")
        self.assertIn("SESSION:chat-agent-789", result.stdout)

    def test_cursor_recovers_chat_id_from_json_when_create_chat_fails(self):
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_NO_CREATE_SCRIPT)
        result = self._run("planner", "write the adr now", SKLC_BACKEND="cursor")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.cursor_log)
        self.assertEqual(invs[0], ["create-chat"])  # attempted, failed
        run = invs[1]
        self.assertNotIn("--resume", run)  # no id: bare run, cursor mints
        self.assertEqual(self._sessions().get("planner"), "chat-from-json")
        self.assertIn("SESSION:chat-from-json", result.stdout)

    def test_cursor_missing_binary_errors(self):
        result = self._run("planner", "write the adr now", SKLC_BACKEND="cursor")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not found in PATH", result.stderr)

    def test_cursor_missing_role_model_errors(self):
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        result = self._run(
            "planner", "write the adr now", SKLC_BACKEND="cursor", SKLC_PLANNER_MODEL=""
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("SKLC_PLANNER_MODEL", result.stderr)

    # -- opencode backend (default) ----------------------------------------

    def test_opencode_default_dispatch_and_resume(self):
        _write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        result = self._run("planner", "write the adr now")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.opencode_log)
        self.assertEqual(
            invs[0],
            ["run", "--agent", "planner", "--auto", "--format", "json", "write the adr now"],
        )
        self.assertEqual(self._sessions().get("planner"), "sess-abc")
        self.assertIn("SESSION:sess-abc", result.stdout)
        # Second call resumes the saved session and stays on the bare prompt.
        self._run("planner", "continue please")
        invs = read_invocations(self.opencode_log)
        self.assertEqual(
            invs[1],
            ["run", "--session", "sess-abc", "--agent", "planner", "--auto",
             "--format", "json", "continue please"],
        )


if __name__ == "__main__":
    unittest.main()
