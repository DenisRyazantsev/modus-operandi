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
fork=0
session=""
while [ $# -gt 0 ]; do
  case "$1" in
    --fork) fork=1 ;;
    --session) session="$2"; shift ;;
  esac
  shift
done
if [ "$fork" = "1" ]; then
  printf '%s\\n' '{"type":"init","sessionID":"sess-fork-1"}'
elif [ "$session" = "sess-gone" ]; then
  # A continued session that no longer exists (opencode auto-compact/cleanup).
  echo "Session not found"
  exit 1
else
  printf '%s\\n' '{"type":"init","sessionID":"sess-abc"}'
fi
"""


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _safe_system_path() -> str:
    # The fakes must shadow any REAL cursor-agent/agent binaries on the host
    # PATH (this machine has both installed): drop the directories that carry
    # them, keep the rest for python3/ps/readlink. The opencode binary is
    # left alone: the opencode branch invokes `opencode` by name and the
    # self.bin fake comes first on PATH, so it already shadows the real one.
    entries = []
    for entry in os.environ["PATH"].split(os.pathsep):
        directory = Path(entry)
        if any((directory / name).exists() for name in ("cursor-agent", "agent")):
            continue
        entries.append(entry)
    return os.pathsep.join(entries)


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
        # run-agent.sh is split one concern per file: the session store and
        # the cursor backend are sourced, prompt_subst.sh is called.
        for name in ("run-agent.sh", "session_store.sh", "run-agent-cursor.sh",
                     "prompt_subst.sh"):
            dst = self.scripts / name
            shutil.copy2(REPO_ROOT / "pipeline_scripts" / name, dst)
            if name in ("run-agent.sh", "prompt_subst.sh"):
                dst.chmod(0o755)
        self.run_agent = self.scripts / "run-agent.sh"
        (self.scripts / "planner-body.txt").write_text(PLANNER_BODY, encoding="utf-8")
        (self.scripts / "executor-body.txt").write_text(EXECUTOR_BODY, encoding="utf-8")
        self.cursor_log = self.tmp / "cursor.log"
        self.agent_log = self.tmp / "agent.log"
        self.opencode_log = self.tmp / "opencode.log"

    def _env(self, **extra) -> dict:
        env = {
            "PATH": str(self.bin) + os.pathsep + _safe_system_path(),
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


    # -- review fork (ADR-0013): one per-kind session per review check ------

    def test_review_fork_first_call_forks_parent_and_saves_kind_id(self):
        _write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        self._seed_session("planner", "warm-999")
        result = self._run("planner", "review now", "--review-fork", "srp")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.opencode_log)
        self.assertEqual(
            invs[0],
            ["run", "--session", "warm-999", "--fork", "--agent", "planner",
             "--auto", "--format", "json", "review now"],
        )
        # The fork's id is saved to the per-kind file, never to the per-role
        # store: the parent warm session stays authoritative.
        kind_file = self.state / "sessions-review-srp.json"
        self.assertEqual(
            json.loads(kind_file.read_text(encoding="utf-8"))["planner"],
            "sess-fork-1",
        )
        self.assertEqual(self._sessions().get("planner"), "warm-999")
        self.assertIn("SESSION:sess-fork-1", result.stdout)
        # Stable per-kind log/pid files: the tailer labels the live line
        # [planner#srp] and the token sums continue between iterations.
        self.assertTrue(
            (self.state / "logs" / "sessions-planner-fork-srp.jsonl").is_file()
        )
        self.assertTrue(
            (self.state / "pids" / "sessions-planner-fork-srp.pid").is_file()
        )

    def test_review_fork_second_call_continues_without_fork(self):
        _write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        self._seed_session("planner", "warm-999")
        kind_file = self.state / "sessions-review-srp.json"
        kind_file.write_text(json.dumps({"planner": "sess-fork-1"}), encoding="utf-8")
        result = self._run("planner", "review again", "--review-fork", "srp")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.opencode_log)
        self.assertEqual(
            invs[0],
            ["run", "--session", "sess-fork-1", "--agent", "planner",
             "--auto", "--format", "json", "review again"],
        )
        # The id is not re-saved (it did not change); the parent store is
        # untouched.
        self.assertEqual(
            json.loads(kind_file.read_text(encoding="utf-8"))["planner"],
            "sess-fork-1",
        )
        self.assertEqual(self._sessions().get("planner"), "warm-999")
        self.assertIn("SESSION:sess-fork-1", result.stdout)

    def test_review_fork_vanished_session_clears_id_and_reforks_parent(self):
        # A continue that fails with "Session not found" (opencode
        # auto-compact/cleanup) drops the per-kind id and forks the parent
        # again (ADR-0013).
        _write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        self._seed_session("planner", "warm-999")
        kind_file = self.state / "sessions-review-srp.json"
        kind_file.write_text(json.dumps({"planner": "sess-gone"}), encoding="utf-8")
        result = self._run("planner", "review again", "--review-fork", "srp")
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.opencode_log)
        self.assertEqual(
            invs[0],
            ["run", "--session", "sess-gone", "--agent", "planner",
             "--auto", "--format", "json", "review again"],
        )
        self.assertEqual(
            invs[1],
            ["run", "--session", "warm-999", "--fork", "--agent", "planner",
             "--auto", "--format", "json", "review again"],
        )
        self.assertEqual(
            json.loads(kind_file.read_text(encoding="utf-8"))["planner"],
            "sess-fork-1",
        )
        self.assertIn("SESSION:sess-fork-1", result.stdout)

    def test_review_fork_without_warm_session_errors(self):
        _write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        result = self._run("planner", "review now", "--review-fork", "srp")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no warm session to fork", result.stderr)

    def test_review_fork_with_prompt_file_parses_flags_in_any_order(self):
        # The parallel fan-out invokes `planner --review-fork <kind>
        # --prompt-file <path>` (ADR-0013): --prompt-file must be recognized
        # at any position, not only as the second argument, or the leftover
        # flag hits usage().
        _write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        self._seed_session("planner", "warm-999")
        prompt = self.tmp / "review.md"
        prompt.write_text("review now", encoding="utf-8")
        result = self._run("planner", "--review-fork", "srp", "--prompt-file", str(prompt))
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.opencode_log)
        self.assertEqual(
            invs[0],
            ["run", "--session", "warm-999", "--fork", "--agent", "planner",
             "--auto", "--format", "json", "review now"],
        )
        kind_file = self.state / "sessions-review-srp.json"
        self.assertEqual(
            json.loads(kind_file.read_text(encoding="utf-8"))["planner"],
            "sess-fork-1",
        )

    def test_review_fork_invalid_kind_errors(self):
        _write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        result = self._run("planner", "review now", "--review-fork", "srp bad!")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid --review-fork", result.stderr)

    def test_review_fork_files_scoped_by_task_id(self):
        _write_executable(self.bin / "opencode", OPENCODE_SCRIPT)
        # The parent warm session is task-scoped too: sessions-task-42.json.
        (self.state / "sessions-task-42.json").write_text(
            json.dumps({"planner": "warm-999"}), encoding="utf-8"
        )
        result = self._run(
            "planner", "review now", "--review-fork", "bugs", "--task", "task-42"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        kind_file = self.state / "sessions-task-42-review-bugs.json"
        self.assertEqual(
            json.loads(kind_file.read_text(encoding="utf-8"))["planner"],
            "sess-fork-1",
        )
        self.assertTrue(
            (self.state / "logs" / "sessions-task-42-planner-fork-bugs.jsonl").is_file()
        )

    def test_cursor_review_fork_first_call_mints_and_saves_kind_chat(self):
        # cursor-agent has no fork primitive (ADR-0013, documented in
        # run-agent-cursor.sh): the per-kind chat IS the fork. The first
        # check of a kind mints a fresh chat, saves its id to the per-kind
        # file (never to the shared store) and prefixes the role body.
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        self._seed_session("planner", "warm-456")
        result = self._run(
            "planner", "review now", "--review-fork", "srp", SKLC_BACKEND="cursor"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.cursor_log)
        self.assertEqual(invs[0], ["create-chat"])
        run = invs[1]
        self.assertEqual(run[9], "--resume")
        self.assertEqual(run[10], "chat-fresh-123")  # the per-kind chat
        self.assertTrue(run[-1].startswith(PLANNER_BODY))
        # The per-kind chat id lands in the per-kind file; the warm parent
        # chat id stays in the shared store, untouched.
        kind_file = self.state / "sessions-review-srp.json"
        self.assertEqual(
            json.loads(kind_file.read_text(encoding="utf-8"))["planner"],
            "chat-fresh-123",
        )
        self.assertEqual(self._sessions().get("planner"), "warm-456")
        self.assertIn("SESSION:chat-fresh-123", result.stdout)

    def test_cursor_review_fork_resumes_saved_kind_chat(self):
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        self._seed_session("planner", "warm-456")
        kind_file = self.state / "sessions-review-srp.json"
        kind_file.write_text(json.dumps({"planner": "chat-srp-1"}), encoding="utf-8")
        result = self._run(
            "planner", "review again", "--review-fork", "srp", SKLC_BACKEND="cursor"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.cursor_log)
        self.assertEqual([i[0] for i in invs], ["-p"])  # no create-chat
        run = invs[0]
        self.assertEqual(run[9], "--resume")
        self.assertEqual(run[10], "chat-srp-1")
        # Resumed chats are hot: the bare prompt, no role body.
        self.assertEqual(run[-1], "review again")
        self.assertEqual(self._sessions().get("planner"), "warm-456")
        self.assertIn("SESSION:chat-srp-1", result.stdout)

    def test_cursor_review_fork_recovers_kind_chat_when_create_chat_fails(self):
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_NO_CREATE_SCRIPT)
        self._seed_session("planner", "warm-456")
        result = self._run(
            "planner", "review now", "--review-fork", "srp", SKLC_BACKEND="cursor"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        invs = read_invocations(self.cursor_log)
        self.assertEqual(invs[0], ["create-chat"])  # attempted, failed
        run = invs[1]
        self.assertNotIn("--resume", run)  # no id: bare run, cursor mints
        self.assertTrue(run[-1].startswith(PLANNER_BODY))
        kind_file = self.state / "sessions-review-srp.json"
        self.assertEqual(
            json.loads(kind_file.read_text(encoding="utf-8"))["planner"],
            "chat-from-json",
        )
        self.assertEqual(self._sessions().get("planner"), "warm-456")
        self.assertIn("SESSION:chat-from-json", result.stdout)

    def test_cursor_review_fork_log_accumulates_across_iterations(self):
        # Regression (ADR-0013 bug fix): the per-kind cursor log is a stable
        # file and must ACCUMULATE across the review-fix-loop iterations —
        # the end-of-run statistics (collect_cursor_usage) sums every event
        # of the file, so truncating on each call would drop all but the
        # last iteration's tokens.
        _write_executable(self.bin / "cursor-agent", CURSOR_AGENT_SCRIPT)
        self._seed_session("planner", "warm-456")
        first = self._run(
            "planner", "review now", "--review-fork", "srp", SKLC_BACKEND="cursor"
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self._run(
            "planner", "review again", "--review-fork", "srp", SKLC_BACKEND="cursor"
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        log = self.state / "logs" / "sessions-planner-fork-srp.jsonl"
        self.assertTrue(log.is_file())
        events = [
            line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        # One result event per invocation, both preserved.
        self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
