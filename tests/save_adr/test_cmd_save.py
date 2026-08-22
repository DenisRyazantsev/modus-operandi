"""Tests for save_adr.cmd_save against a real run-agent.sh script.

The planner round-trip goes through a real subprocess: a real shell script
sits in place of run-agent.sh and either edits the ADR (adding the slug)
or fails, so the ask/refuse/fail paths of save_adr are exercised for real.
"""

import argparse
import tempfile
import unittest
from pathlib import Path

from tests.env_sandbox import env

from .helpers import save_adr


class CmdSaveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task_dir = self.root / ".workflow" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)
        self.run_agent = self.root / "run-agent.sh"

    def _write_agent(self, body: str) -> None:
        self.run_agent.write_text(body)
        self.run_agent.chmod(0o755)

    def adr(self, text: str) -> None:
        (self.task_dir / "adr.md").write_text(text, encoding="utf-8")

    def save(self, task_id: str = "t1") -> None:
        save_adr.cmd_save(
            argparse.Namespace(
                state_dir=str(self.root / ".workflow"),
                task_id=task_id,
                adr_dir=str(self.root / "architecture"),
                run_agent=str(self.run_agent),
            )
        )

    def test_save_with_slug_creates_adr(self) -> None:
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты\n")
        self.save()
        saved = self.root / "architecture" / "ADR-0001-prod-validation-splits.md"
        self.assertTrue(saved.exists())
        self.assertIn("# ADR-0001: Сплиты", saved.read_text(encoding="utf-8"))
        saved_txt = (self.task_dir / "adr-saved.txt").read_text(encoding="utf-8")
        self.assertEqual(saved_txt, str(saved))

    def test_save_is_idempotent_by_slug(self) -> None:
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты\n")
        self.save()
        self.save()
        files = list((self.root / "architecture").glob("ADR-*.md"))
        self.assertEqual(len(files), 1)

    def test_missing_slug_asks_planner(self) -> None:
        # The real script is the planner: it edits adr.md (adds the slug)
        # and exits 0.
        self.adr("---\nstatus: accepted\n---\n# ADR: Сплиты\n")
        self._write_agent(
            "#!/bin/sh\n"
            'if [ -n "$ADR_PATH" ]; then\n'
            "  sed -i 's/status: accepted/slug: prod-validation-splits\\nstatus: accepted/'"
            ' "$ADR_PATH"\n'
            "fi\nexit 0\n"
        )
        with env({"ADR_PATH": str(self.task_dir / "adr.md")}):
            self.save()
        saved = self.root / "architecture" / "ADR-0001-prod-validation-splits.md"
        self.assertTrue(saved.exists())

    def test_planner_refusal_fails(self) -> None:
        # The script succeeds but changes nothing: the still-missing slug
        # surfaces as a readable error, not a silent save.
        self.adr("---\nstatus: accepted\n---\n# ADR: Сплиты\n")
        self._write_agent("#!/bin/sh\nexit 0\n")
        with self.assertRaises(SystemExit) as cm:
            self.save()
        self.assertIn("slug", str(cm.exception))
        self.assertFalse((self.root / "architecture").exists())

    def test_agent_transport_failure_is_readable(self) -> None:
        # The script crashes with a non-zero exit: the error surfaces
        # run-agent.sh's message, not a raw CalledProcessError traceback.
        self.adr("---\nstatus: accepted\n---\n# ADR: Сплиты\n")
        self._write_agent(
            "#!/bin/sh\necho 'run-agent: opencode exited 2; full log: /tmp/x.jsonl' >&2\nexit 2\n"
        )
        with self.assertRaises(SystemExit) as cm:
            self.save()
        message = str(cm.exception)
        self.assertIn("agent call failed (exit 2)", message)
        self.assertIn("full log: /tmp/x.jsonl", message)
        self.assertNotIn("Traceback", message)

    def test_rerun_same_task_reuses_own_file(self) -> None:
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты\n")
        self.save()
        self.adr("---\nslug: prod-validation-splits\n---\n# ADR: Сплиты v2\n")
        self.save()
        files = list((self.root / "architecture").glob("ADR-*.md"))
        self.assertEqual(len(files), 1)

    def test_same_slug_different_task_is_collision_not_reuse(self) -> None:
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
            self.save(task_id="t2")
        self.assertIn("used by another task", str(cm.exception))
        self.assertFalse((t2 / "adr-saved.txt").exists())
        self.assertIn("# ADR-0001: Сплиты t1", saved.read_text(encoding="utf-8"))

    def test_ask_planner_uses_list_form(self) -> None:
        # The list-form invocation keeps a path with spaces as one argv
        # element (a shell=True join would split it): the script logs its
        # arguments, and the recorded argv is the real one. The path with
        # spaces itself ran without FileNotFoundError.
        log = self.root / "args.log"
        agent = self.root / "run agent.sh"
        agent.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\nexit 0\n')
        agent.chmod(0o755)
        save_adr._ask_planner_for_slug(Path("/tmp/t1/adr.md"), str(agent), "t1")
        args = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(args[0], "planner")
        self.assertEqual(args[-2:], ["--task", "t1"])
        # The prompt with spaces stayed a single argv element.
        self.assertIn("Read /tmp/t1/adr.md.", args[1])

    def test_save_via_symlink_is_idempotent(self) -> None:
        tasks = self.root / ".workflow" / "tasks"
        (tasks / "auto-1").mkdir()
        (tasks / "current").symlink_to("auto-1")
        (tasks / "auto-1" / "adr.md").write_text(
            "---\nslug: auto-feature\n---\n# ADR: Авто\n", encoding="utf-8"
        )

        def save_empty_id() -> None:
            save_adr.cmd_save(
                argparse.Namespace(
                    state_dir=str(self.root / ".workflow"),
                    task_id="",
                    adr_dir=str(self.root / "architecture"),
                    run_agent=str(self.run_agent),
                )
            )

        save_empty_id()
        save_empty_id()
        files = list((self.root / "architecture").glob("ADR-*.md"))
        self.assertEqual(len(files), 1)
        self.assertTrue((tasks / "auto-1" / "adr-saved.txt").exists())
