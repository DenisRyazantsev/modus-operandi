"""InstallerTestCase: shared fixture for every installer test."""

from __future__ import annotations

import io
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

from modus_operandi import installer_cli as install
from modus_operandi import proc, tool_discovery, yaml_loader

from .install_helpers import make_run, which_fake


class InstallerTestCase(unittest.TestCase):
    """Shared fixture for every install test: a fresh --home temp dir and a
    faked external-command layer, plus the helpers the focused test classes
    use to drive the installer."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.records: list[list[str]] = []
        patcher = mock.patch.object(proc, "run", side_effect=make_run(self.records))
        patcher.start()
        self.addCleanup(patcher.stop)

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
        which: Callable[[str], str | None] = which_fake,
    ) -> tuple[int, str]:
        stderr = io.StringIO()
        with (
            mock.patch.object(tool_discovery, "find_in_path", side_effect=which),
            mock.patch("sys.stderr", stderr),
        ):
            rc = install.main(argv)
        return rc, stderr.getvalue()

    def install(self, *extra: str) -> int:
        return self.run_main(["--home", str(self.home), *extra])[0]

    def read_config(self) -> str:
        path = self.home / ".config" / "modus-operandi" / "config.yml"
        return path.read_text(encoding="utf-8")

    def write_config(self, text: str) -> None:
        path = self.home / ".config" / "modus-operandi" / "config.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
