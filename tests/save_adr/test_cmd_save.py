"""Unit tests for save_adr.cmd_save."""

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .failed_result import FailedResult
from .fake_result import FakeResult
from .helpers import save_adr


class CmdSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)

    def adr(self, text):
        (self.task_dir / "adr.md").write_text(text, encoding="utf-8")

    def save(self):
        save_adr.cmd_save(
            argparse.Namespace(
                state_dir=str(self.root / ".workflow"),
                task_id="t1",
                adr_dir=str(self.root / "architecture"),
                run_agent="/nonexistent/run-agent.sh",
            )
        )

    def test_save_with_slug_creates_adr(self):
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты\n")
        self.save()
        saved = self.root / "architecture" / "ADR-0001-prod-validation-splits.md"
        self.assertTrue(saved.exists())
        self.assertIn("# ADR-0001: Сплиты", saved.read_text(encoding="utf-8"))
        saved_txt = (self.task_dir / "adr-saved.txt").read_text(encoding="utf-8")
        self.assertEqual(saved_txt, str(saved))

    def test_save_is_idempotent_by_slug(self):
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты\n")
        self.save()
        self.save()
        files = list((self.root / "architecture").glob("ADR-*.md"))
        self.assertEqual(len(files), 1)

    def test_missing_slug_asks_planner(self):
        self.adr("---\nstatus: accepted\n---\n# ADR: Сплиты\n")

        def fake_run(cmd, text=True, capture_output=True):
            assert text is True and capture_output is True
            assert "planner" in cmd
            adr = self.task_dir / "adr.md"
            text = adr.read_text(encoding="utf-8")
            adr.write_text(
                text.replace("status: accepted", "slug: prod-validation-splits\nstatus: accepted"),
                encoding="utf-8",
            )
            return FakeResult()

        with mock.patch("subprocess.run", side_effect=fake_run):
            self.save()
        saved = self.root / "architecture" / "ADR-0001-prod-validation-splits.md"
        self.assertTrue(saved.exists())

    def test_planner_refusal_fails(self):
        self.adr("---\nstatus: accepted\n---\n# ADR: Сплиты\n")
        with mock.patch("subprocess.run", return_value=FakeResult()), self.assertRaises(
            SystemExit
        ) as cm:
            self.save()
        self.assertIn("slug", str(cm.exception))

    def test_agent_transport_failure_is_readable(self):
        # If the planner process itself fails (crash, timeout, attach
        # failure), the error must surface run-agent.sh's message, not a raw
        # CalledProcessError traceback.
        self.adr("---\nstatus: accepted\n---\n# ADR: Сплиты\n")
        with mock.patch("subprocess.run", return_value=FailedResult()), self.assertRaises(
            SystemExit
        ) as cm:
            self.save()
        message = str(cm.exception)
        self.assertIn("agent call failed (exit 2)", message)
        self.assertIn("full log: /tmp/x.jsonl", message)
        self.assertNotIn("Traceback", message)

    def test_rerun_same_task_reuses_own_file(self):
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты\n")
        self.save()
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты v2\n")
        self.save()
        files = list((self.root / "architecture").glob("ADR-*.md"))
        self.assertEqual(len(files), 1)

    def test_same_slug_different_task_is_collision_not_reuse(self):
        t2 = self.root / ".workflow" / "tasks" / "t2"
        t2.mkdir()
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты t1\n")
        self.save()
        saved = self.root / "architecture" / "ADR-0001-prod-validation-splits.md"
        (t2 / "adr.md").write_text(
            "---\nslug: prod-validation-splits\n---\n# ADR: Сплиты t2\n",
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit) as cm:
            save_adr.cmd_save(
                argparse.Namespace(
                    state_dir=str(self.root / ".workflow"),
                    task_id="t2",
                    adr_dir=str(self.root / "architecture"),
                    run_agent="/nonexistent/run-agent.sh",
                )
            )
        self.assertIn("used by another task", str(cm.exception))
        self.assertFalse((t2 / "adr-saved.txt").exists())
        self.assertIn("# ADR-0001: Сплиты t1", saved.read_text(encoding="utf-8"))

    def test_ask_planner_uses_list_form(self):
        recorded = {}

        def fake_run(cmd, text=True, capture_output=True):
            recorded["cmd"] = cmd
            return FakeResult()

        with mock.patch("subprocess.run", side_effect=fake_run):
            save_adr._ask_planner_for_slug(
                Path("/tmp/t1/adr.md"), "/path with spaces/run-agent.sh", "t1"
            )
        self.assertEqual(recorded["cmd"][0], "/path with spaces/run-agent.sh")
        self.assertEqual(recorded["cmd"][1], "planner")
        self.assertEqual(recorded["cmd"][-2:], ["--task", "t1"])

    def test_save_via_symlink_is_idempotent(self):
        tasks = self.root / ".workflow" / "tasks"
        (tasks / "auto-1").mkdir()
        (tasks / "current").symlink_to("auto-1")
        (tasks / "auto-1" / "adr.md").write_text(
            "---\nslug: auto-feature\n---\n# ADR: Авто\n", encoding="utf-8"
        )

        def save_empty_id():
            save_adr.cmd_save(
                argparse.Namespace(
                    state_dir=str(self.root / ".workflow"),
                    task_id="",
                    adr_dir=str(self.root / "architecture"),
                    run_agent="/nonexistent/run-agent.sh",
                )
            )

        save_empty_id()
        save_empty_id()
        files = list((self.root / "architecture").glob("ADR-*.md"))
        self.assertEqual(len(files), 1)
        self.assertTrue((tasks / "auto-1" / "adr-saved.txt").exists())
