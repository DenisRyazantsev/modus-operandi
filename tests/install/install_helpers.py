"""Faked external-command layer for the installer tests."""

from collections.abc import Callable
from pathlib import Path

from .fake_result import FakeResult

_COMMANDS = {
    "opencode": "/usr/bin/opencode",
    "python3": "/usr/bin/python3",
    "specify": "/usr/bin/specify",
    "cursor-agent": "/usr/bin/cursor-agent",
    "agent": "/usr/bin/agent",
}


def make_run(
    records: list[list[str]] | None = None,
) -> Callable[[list[str], str | Path | None, dict[str, str] | None, bool], FakeResult]:
    def _run(
        cmd: list[str],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> FakeResult:
        if records is not None:
            records.append(list(cmd))
        if cmd[-1] == "--version" and "specify" in cmd[0]:
            return FakeResult(0, "specify-cli 0.16.2\n")
        if cmd[1:3] == ["workflow", "run"]:
            return FakeResult(1, "", "Error: Required input 'feature' not provided.\n")
        if cmd[-3:] == ["opencode", "agent", "list"]:
            return FakeResult(0, "build (primary)\nplanner (subagent)\nexecutor (subagent)\n")
        return FakeResult(0)

    return _run


def which_fake(name: str) -> str | None:
    return _COMMANDS.get(name)
