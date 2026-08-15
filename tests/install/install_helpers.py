"""Faked external-command layer for the installer tests."""

from .fake_result import FakeResult


def make_run(records=None):
    def _run(cmd, cwd=None, env=None, check=True):
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


def which_fake(name):
    return {
        "opencode": "/usr/bin/opencode",
        "python3": "/usr/bin/python3",
        "specify": "/usr/bin/specify",
    }.get(name)
