"""RunIdDiscoverer: find the run directory created since the wrapper started."""

from __future__ import annotations

from pathlib import Path

from _run_pipeline_common import existing_run_ids


class RunIdDiscoverer:
    """Find the run id of the workflow this wrapper started.

    `specify workflow run` prints "Run ID: <id>" only AFTER the workflow
    finishes, so during the run the id can only come from the run directory
    that appeared under .specify/workflows/runs/ since the wrapper started.
    The prior-run snapshot (taken BEFORE the workflow starts) is the
    baseline: everything newer than it belongs to this invocation. Guessing
    by newest mtime is not reliable either — a resumed run keeps its
    original mtime, and a concurrent run could be newer.
    """

    def __init__(self, run_state_dir: Path, prior_runs: set[str]) -> None:
        self._run_state_dir = run_state_dir
        self._prior_runs = prior_runs

    def discover(self) -> str:
        """Return the id of the first new run directory, or "" when none yet."""
        for name in sorted(existing_run_ids(self._run_state_dir) - self._prior_runs):
            return name
        return ""
