"""FailedResult: a stand-in for a failing subprocess result."""


class FailedResult:
    returncode = 2
    stdout = ""
    stderr = "run-agent: opencode exited 2; full log: /tmp/x.jsonl\n"
