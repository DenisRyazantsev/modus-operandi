"""InstallerTestCase: shared fixture for every installer test."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from modus_operandi import installer_cli as install
from modus_operandi import proc, yaml_loader
from tests.env_sandbox import env, stderr

from .install_helpers import make_run


class InstallerTestCase(unittest.TestCase):
    """Shared fixture for every install test: a fresh --home temp dir, real
    tool binaries on PATH and the faked external-command layer (proc.run —
    the installer's real subprocesses would run the engine; see
    workspace.md)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.records: list[list[str]] = []
        patcher = mock.patch.object(proc, "run", side_effect=make_run(self.records))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self._make_bins("opencode", "python3", "specify", "cursor-agent", "agent")

    def _make_bins(self, *names: str) -> None:
        for name in names:
            path = self.bin / name
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def parsed_workflow(self, rel: str = ".config/modus-operandi/review-pipeline.yml") -> Any:
        return yaml_loader.yaml.safe_load((self.home / rel).read_text(encoding="utf-8"))

    def find_step(self, steps: Any, step_id: str) -> Any:
        """Recursively find a step by id in the parsed workflow steps."""
        for step in steps:
            if step.get("id") == step_id:
                return step
            for branch in ("steps", "then", "else"):
                nested = step.get(branch)
                if isinstance(nested, list):
                    found = self.find_step(nested, step_id)
                    if found is not None:
                        return found
        return None

    def run_main(
        self,
        argv: list[str],
        missing: tuple[str, ...] = (),
    ) -> tuple[int, str]:
        # The tool lookup is real: PATH is the temp bin dir (the host's
        # binaries are deliberately excluded), with the given tools removed
        # to simulate "not installed".
        for name in missing:
            (self.bin / name).unlink()
        err_sink = io.StringIO()
        with env({"PATH": str(self.bin)}, clear=True), stderr(err_sink):
            rc = install.main(argv)
        return rc, err_sink.getvalue()

    def install(self, *extra: str) -> int:
        return self.run_main(["--home", str(self.home), *extra])[0]

    def read_config(self) -> str:
        path = self.home / ".config" / "modus-operandi" / "config.yml"
        return path.read_text(encoding="utf-8")

    def write_config(self, text: str) -> None:
        path = self.home / ".config" / "modus-operandi" / "config.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
