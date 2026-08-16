"""AgentLogTailer: tail the per-role agent logs (<state_dir>/logs/*.jsonl)."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from _run_pipeline_common import render_log_event


class AgentLogTailer:
    """Tails the per-role agent logs (<state_dir>/logs/*.jsonl).

    Construction (which happens before the workflow process starts) takes a
    baseline snapshot of the current sizes of every existing *.jsonl file:
    those files were written by previous runs (the logs dir is never
    cleaned), so each starts at its baseline offset and only lines appended
    during the current run are printed. Files created after the baseline
    start at offset 0.
    """

    def __init__(self, logs_dir: Path) -> None:
        self._logs_dir = logs_dir
        self._log_pos: dict[Path, int] = {}
        if logs_dir.is_dir():
            for path in sorted(logs_dir.glob("*.jsonl")):
                with contextlib.suppress(OSError):
                    self._log_pos[path] = path.stat().st_size

    def tail(self) -> list[tuple[str, str]]:
        """Return (role, text) pairs for log lines appended since the last tail.

        Raw file reading (byte offsets) lives in _read_appended(); the
        interpretation of each line into a (role, text) pair is the pure
        render_log_event().
        """
        if not self._logs_dir.is_dir():
            return []
        events: list[tuple[str, str]] = []
        for path in sorted(self._logs_dir.glob("*.jsonl")):
            lines, _ = self._read_appended(path)
            if not lines:
                continue
            # Parallel review forks write per-invocation log files
            # (sessions-<task>-<role>-fork-<pid>.jsonl, see run-agent.sh): strip
            # the -fork-<pid> suffix so the role is still derived from the log
            # file's last dash segment.
            stem = re.sub(r"-fork-\d+$", "", path.stem)
            role = stem.rsplit("-", 1)[-1]
            for line in lines:
                # The role is fixed per log file; render_log_event maps the
                # line to a (role, text) pair and never varies the role.
                _, text = render_log_event(role, line)
                if text:
                    events.append((role, text))
        return events

    def _read_appended(self, path: Path) -> tuple[list[str], int]:
        """Read the lines appended to path since the last tail.

        Returns (lines, new_offset). Tracks raw byte offsets per log file so
        each line is yielded exactly once even when the file grows between
        polls; the lines are returned uninterpreted. A trailing line without
        a terminating newline (an in-progress write) is NOT consumed — it is
        re-read on the next poll, so a half-written JSON event is never
        rendered as a broken raw line. The recorded offset advances only
        after a successful read, so a transient OSError cannot permanently
        skip a chunk.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return [], self._log_pos.get(path, 0)
        offset = self._log_pos.get(path, 0)
        if size < offset:
            offset = 0
        if size <= offset:
            return [], offset
        try:
            with path.open(encoding="utf-8") as fh:
                fh.seek(offset)
                data = fh.read()
        except OSError:
            # Position unchanged: the same chunk is retried next poll.
            return [], self._log_pos.get(path, 0)
        if not data:
            return [], offset
        last_nl = data.rfind("\n")
        if last_nl == -1:
            # Only an unterminated line: nothing complete to consume.
            return [], offset
        complete = data[: last_nl + 1]
        lines = complete.splitlines()
        # Offsets are BYTE offsets: they come from path.stat().st_size and are
        # fed to fh.seek(). len(complete) counts characters, so re-encode to
        # get the byte length — otherwise multibyte UTF-8 lines (e.g. Russian
        # ADR text in the agent events) make new_offset land mid-character,
        # and the next poll's fh.read() raises UnicodeDecodeError (a
        # ValueError, which the except OSError above does not catch), killing
        # the tailer thread.
        new_offset = offset + len(complete.encode("utf-8"))
        self._log_pos[path] = new_offset
        return lines, new_offset
