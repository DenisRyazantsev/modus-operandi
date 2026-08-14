"""Unit tests for versions.latest_specify_version()."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spec_utils import versions


class FakeResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class LatestSpecifyVersionTest(unittest.TestCase):
    OLD = "/home/u/.local/bin/specify"
    MID = "/home/u/.local/share/uv/tools/specify-cli/bin/specify"
    NEW = "/usr/bin/specify"

    def fake_run(self, versions_by_path):
        def _run(cmd, cwd=None, env=None, check=True):
            return FakeResult(0, f"specify-cli {versions_by_path[cmd[0]]}\n")

        return _run

    def test_returns_newest_candidate_not_first_in_probe_order(self):
        # Probe order is (~/.local/bin, uv tools, PATH), which is not version
        # order: the OLD binary comes first and must not win.
        with (
            mock.patch.object(
                versions, "_specify_candidates", return_value=[self.OLD, self.MID]
            ),
            mock.patch.object(
                versions.tool_discovery, "find_in_path", return_value=self.NEW
            ),
            mock.patch.object(
                versions.proc,
                "run",
                side_effect=self.fake_run(
                    {self.OLD: "0.15.2", self.MID: "0.17.2", self.NEW: "0.16.9"}
                ),
            ),
        ):
            version, path = versions.latest_specify_version()
        self.assertEqual(version, (0, 17))
        self.assertEqual(path, self.MID)

    def test_newest_on_path_wins(self):
        with (
            mock.patch.object(
                versions, "_specify_candidates", return_value=[self.OLD, self.MID]
            ),
            mock.patch.object(
                versions.tool_discovery, "find_in_path", return_value=self.NEW
            ),
            mock.patch.object(
                versions.proc,
                "run",
                side_effect=self.fake_run(
                    {self.OLD: "0.18.0", self.MID: "0.17.2", self.NEW: "0.19.0"}
                ),
            ),
        ):
            version, path = versions.latest_specify_version()
        self.assertEqual(version, (0, 19))
        self.assertEqual(path, self.NEW)

    def test_unparseable_output_yields_none(self):
        with (
            mock.patch.object(versions, "_specify_candidates", return_value=[self.OLD]),
            mock.patch.object(versions.tool_discovery, "find_in_path", return_value=None),
            mock.patch.object(
                versions.proc,
                "run",
                side_effect=self.fake_run({self.OLD: "garbage output"}),
            ),
        ):
            version, path = versions.latest_specify_version()
        self.assertIsNone(version)
        self.assertIsNone(path)

    def test_failed_probe_is_skipped(self):
        def _run(cmd, cwd=None, env=None, check=True):
            if cmd[0] == self.OLD:
                return FakeResult(1)
            return FakeResult(0, "specify-cli 0.16.1\n")

        with (
            mock.patch.object(
                versions, "_specify_candidates", return_value=[self.OLD, self.MID]
            ),
            mock.patch.object(versions.tool_discovery, "find_in_path", return_value=None),
            mock.patch.object(versions.proc, "run", side_effect=_run),
        ):
            version, path = versions.latest_specify_version()
        self.assertEqual(version, (0, 16))
        self.assertEqual(path, self.MID)


if __name__ == "__main__":
    unittest.main()
