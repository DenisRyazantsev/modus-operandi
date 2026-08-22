"""E2E: the built wheel bootstraps a working installation.

`uv build` -> install the wheel into a temp venv -> run the entry point with
an isolated XDG_CONFIG_HOME -> assert the rendered layout, the version marker
and the no-re-render / config-preservation guarantees (AC 1, 3, 4).
"""

import os
import shutil
import socket
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _network_available() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=5).close()
        return True
    except OSError:
        return False


@unittest.skipUnless(shutil.which("uv"), "uv not available")
class WheelBootstrapTest(unittest.TestCase):
    """Build the wheel, inspect it, install it and run the entry point."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dist = self.root / "dist"
        self.venv = self.root / "venv"
        self.xdg = self.root / "xdg"
        self.bin = self.root / "bin"
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)

    def _build(self) -> Path:
        result = self._run(["uv", "build", "--out-dir", str(self.dist)])
        self.assertEqual(result.returncode, 0, result.stderr)
        wheels = list(self.dist.glob("*.whl"))
        self.assertEqual(len(wheels), 1)
        return wheels[0]

    @unittest.skipUnless(_network_available(), "network required for uv build")
    def test_wheel_contains_package_data(self) -> None:
        wheel = self._build()
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
        for needle in (
            "modus_operandi/data/pipeline_scripts/run_pipeline.py",
            "modus_operandi/data/pipeline_scripts/editor.py",
            "modus_operandi/data/pipeline_scripts/run-agent.sh",
            "modus_operandi/data/prompts/adr/write-adr.md",
            "modus_operandi/data/prompts/task/study.md",
            "modus_operandi/data/workflows/task-pipeline.yml",
            "modus_operandi/data/workflows/review-pipeline.yml",
            "modus_operandi/data/config.example.yml",
            "modus_operandi/data/victory.wav",
            "modus_operandi/cli.py",
            # The MIT license text ships in the wheel (PEP 639 license-files).
            "modus_operandi-0.1.0.dist-info/licenses/LICENSE",
        ):
            self.assertIn(needle, names, needle)
        # The standalone adr pipeline is not shipped.
        self.assertNotIn("modus_operandi/data/workflows/adr-pipeline.yml", names)

    @unittest.skipUnless(_network_available(), "network required to install the wheel")
    def test_wheel_bootstrap_end_to_end(self) -> None:
        wheel = self._build()
        result = self._run(["uv", "venv", str(self.venv)])
        self.assertEqual(result.returncode, 0, result.stderr)
        venv_python = self.venv / "bin" / "python"
        result = self._run(["uv", "pip", "install", "--python", str(venv_python), str(wheel)])
        self.assertEqual(result.returncode, 0, result.stderr)

        # A fake backend CLI satisfies the bootstrap prerequisite check.
        self.bin.mkdir()
        fake = self.bin / "opencode"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["XDG_CONFIG_HOME"] = str(self.xdg)
        modus_operandi = self.venv / "bin" / "modus-operandi"
        self.assertTrue(modus_operandi.exists())

        # First run: the bootstrap renders everything and prints one status
        # line (the run itself fails on the fake backend - not asserted).
        first = subprocess.run(
            [str(modus_operandi), "review"],
            env=env,
            cwd=str(self.run_dir),
            capture_output=True,
            text=True,
        )
        self.assertIn("modus-operandi: installed to", first.stdout)
        self.assertIn(str(self.xdg / "modus-operandi"), first.stdout)

        for rel in (
            "modus-operandi/config.yml",
            "modus-operandi/config.example.yml",
            "modus-operandi/task-pipeline.yml",
            "modus-operandi/review-pipeline.yml",
            "modus-operandi/install-version.txt",
            "modus-operandi/prompts/task/study.md",
            "modus-operandi/prompts/adr/write-adr.md",
            "opencode/agent/planner.md",
            "opencode/agent/executor.md",
            "opencode/scripts/run-pipeline.py",
            "opencode/scripts/run-agent.sh",
            "opencode/scripts/victory.wav",
        ):
            self.assertTrue((self.xdg / rel).exists(), rel)

        # Second run with the same version: no re-render, no status line,
        # and a user-edited config.yml survives untouched.
        config = self.xdg / "modus-operandi" / "config.yml"
        config.write_text(config.read_text(encoding="utf-8") + "# USER EDITED\n", encoding="utf-8")
        second = subprocess.run(
            [str(modus_operandi), "review"],
            env=env,
            cwd=str(self.run_dir),
            capture_output=True,
            text=True,
        )
        self.assertNotIn("modus-operandi: installed", second.stdout)
        self.assertNotIn("modus-operandi: updated", second.stdout)
        self.assertIn("# USER EDITED", config.read_text(encoding="utf-8"))
