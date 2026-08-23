"""Tests for the CI version-stamping helper (.github/scripts/set_version.py)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "set_version.py"

PYPROJECT = '[project]\nversion = "0.1.0"\n'
INIT = '"""modus-operandi package."""\n__version__ = "0.1.0"\n'


class SetVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "pyproject.toml").write_text(PYPROJECT)
        init = self.root / "src" / "modus_operandi"
        init.mkdir(parents=True)
        (init / "__init__.py").write_text(INIT)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def test_stamps_version_into_both_files(self) -> None:
        proc = self.run_script("1.2.3")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        pyproject = (self.root / "pyproject.toml").read_text()
        self.assertEqual(pyproject, PYPROJECT.replace('"0.1.0"', '"1.2.3"'))
        self.assertEqual(
            (self.root / "src" / "modus_operandi" / "__init__.py").read_text(),
            INIT.replace('"0.1.0"', '"1.2.3"'),
        )

    def test_requires_exactly_one_argument(self) -> None:
        proc = self.run_script()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("usage", proc.stderr)

    def test_rejects_v_prefixed_tag(self) -> None:
        proc = self.run_script("v1.2.3")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not a valid PEP 440", proc.stderr)

    def test_rejects_non_version_tag(self) -> None:
        proc = self.run_script("release-1")
        self.assertNotEqual(proc.returncode, 0)

    def test_accepts_dev_version_tag(self) -> None:
        proc = self.run_script("0.1.0.dev1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        pyproject = (self.root / "pyproject.toml").read_text()
        self.assertIn('version = "0.1.0.dev1"', pyproject)


if __name__ == "__main__":
    unittest.main()
