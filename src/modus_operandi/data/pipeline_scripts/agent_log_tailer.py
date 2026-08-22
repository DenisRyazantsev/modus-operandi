"""AgentLogTailer: tail the per-role agent logs (<state_dir>/logs/*.jsonl)."""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path


class AgentLogTailer:
    """Tails the per-role agent logs (<state_dir>/logs/*.jsonl).

    Construction (which happens before the workflow process starts) takes a
    baseline snapshot of the current sizes of every existing *.jsonl file:
    those files were written by previous runs (the logs dir is never
    cleaned), so each starts at its baseline offset and only lines appended
    during the current run are yielded. Files created after the baseline
    start at offset 0.
    """

    def __init__(self, logs_dir: Path) -> None:
        self._logs_dir = logs_dir
        self._log_pos: dict[Path, int] = {}
        if logs_dir.is_dir():
            for path in sorted(logs_dir.glob("*.jsonl")):
                with contextlib.suppress(OSError):
                    self._log_pos[path] = path.stat().st_size

    def tail(self) -> list[tuple[str, str, str, dict[str, object] | None]]:
        """Return (role, fork_id, text, event) quadruples for log lines
        appended since the last tail.

        Raw file reading (byte offsets) lives in _read_appended(). The role
        and the fork id come from the log file name (ADR-0011: the parallel
        review forks write per-invocation files, so the live status lines
        can keep separate accumulators), the text is always empty (since
        ADR-0011 nothing is printed from the agent logs — the live status
        lines replace the old log echo) and the event is the parsed JSON
        object of the line (None for a non-JSON line) — the live status
        lines consume the `step_finish` events from it.
        """
        if not self._logs_dir.is_dir():
            return []
        events: list[tuple[str, str, str, dict[str, object] | None]] = []
        for path in sorted(self._logs_dir.glob("*.jsonl")):
            lines, _ = self._read_appended(path)
            if not lines:
                continue
            # The review kinds write stable per-kind log files
            # (sessions-<task>-<role>-fork-<kind>.jsonl, see run-agent.sh,
            # ADR-0013): the -fork-<kind> suffix is stripped for the role
            # and kept as the fork id (the kind), so the live status lines
            # carry separate accumulators labeled [planner#<kind>]. The
            # marker is anchored to the role (not a bare "-fork-"): a task
            # id that itself contains "-fork-" (branch-derived slugs like
            # feature-fork-x) must not misattribute the log — the role is
            # the last segment of the stem, and the real kind only ever
            # follows "-<role>-fork-".
            fork_m = re.search(r"-(planner|executor)-fork-([A-Za-z0-9_-]+)$", path.stem)
            if fork_m:
                role = fork_m.group(1)
                fork_id = fork_m.group(2)
            else:
                role = path.stem.rsplit("-", 1)[-1]
                fork_id = ""
            for line in lines:
                event = None
                with contextlib.suppress(Exception):
                    event = json.loads(line)
                # Nothing is printed from the agent logs anymore (ADR-0011):
                # the text element of the quadruple is always empty.
                events.append((role, fork_id, "", event))
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
