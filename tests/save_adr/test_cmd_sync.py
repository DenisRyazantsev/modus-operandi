"""Unit tests for save_adr.cmd_sync."""

import argparse
import io
import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import stdout

from .helpers import save_adr


class CmdSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)
        self.arch = self.root / "architecture"
        self.arch.mkdir()

    def test_sync_rewrites_heading_from_filename(self) -> None:
        target = self.arch / "ADR-0007-prod-validation-splits.md"
        target.write_text("# ADR-0007: old\n", encoding="utf-8")
        (self.task_dir / "adr-saved.txt").write_text(str(target), encoding="utf-8")
        (self.task_dir / "adr.md").write_text(
            "# ADR: updated title\n## Amendments\n- x\n", encoding="utf-8"
        )
        save_adr.cmd_sync(argparse.Namespace(state_dir=str(self.root / ".workflow"), task_id="t1"))
        out = target.read_text(encoding="utf-8")
        self.assertTrue(out.startswith("# ADR-0007: updated title"))
        self.assertIn("## Amendments", out)

    def test_sync_missing_saved_file_fails(self) -> None:
        with self.assertRaises(SystemExit):
            save_adr.cmd_sync(
                argparse.Namespace(state_dir=str(self.root / ".workflow"), task_id="t1")
            )

    def test_sync_unparseable_saved_path_fails(self) -> None:
        # adr-saved.txt points at a file whose name has no ADR-<number>-:
        # sync must fail loudly instead of writing a malformed "# ADR-XXXX:".
        target = self.arch / "renamed-adr.md"
        target.write_text("# ADR: old\n", encoding="utf-8")
        (self.task_dir / "adr-saved.txt").write_text(str(target), encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            save_adr.cmd_sync(
                argparse.Namespace(state_dir=str(self.root / ".workflow"), task_id="t1")
            )
        self.assertIn("cannot extract ADR number", str(cm.exception))
        # The unparseable target file must be left untouched.
        self.assertIn("# ADR: old", target.read_text(encoding="utf-8"))

    def test_sync_empty_saved_path_warns_not_crashes(self) -> None:
        # Regression: Path("") normalizes to "." (truthy), so the old
        # `not str(Path(...))` guard never fired and an empty adr-saved.txt
        # fell through to the number regex, exiting with the cryptic
        # "cannot extract ADR number from .". The emptiness check must run
        # on the raw string, before the Path is constructed.
        (self.task_dir / "adr-saved.txt").write_text("", encoding="utf-8")
        captured = io.StringIO()
        with stdout(captured):
            save_adr.cmd_sync(
                argparse.Namespace(state_dir=str(self.root / ".workflow"), task_id="t1")
            )
        self.assertIn("warning: saved adr not found", captured.getvalue())
