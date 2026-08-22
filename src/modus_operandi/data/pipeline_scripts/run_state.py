"""Run-state observation: the finished-step statuses and the run-directory snapshot.

One responsibility: observe the specify engine's run state on disk — the
statuses the poller treats as terminal, and the snapshot of the run
directories that already exist before a workflow starts (so a directory
that appears afterwards belongs to this invocation). Consumed by
step_result_poller.py and run_id_discoverer.py.
"""

from __future__ import annotations

from pathlib import Path

# Step statuses the poller treats as finished. Anything else (running,
# pending, queued, unset) means the step is still in progress and must not be
# reported as a finished event.
TERMINAL_STATUSES = frozenset({"completed", "failed", "skipped"})


def existing_run_ids(run_state_dir: Path) -> set[str]:
    """Names of the run directories already present under run_state_dir/runs.

    Snapshot these BEFORE the workflow process starts: a run directory that
    appears afterwards belongs to this invocation, and that is the only
    reliable way to recognize it. Guessing by newest mtime is not reliable
    here either — a resumed run keeps its original mtime, and a concurrent
    run could be newer.
    """
    runs_dir = run_state_dir / "workflows" / "runs"
    try:
        return {p.name for p in runs_dir.iterdir() if p.is_dir()}
    except OSError:
        return set()
