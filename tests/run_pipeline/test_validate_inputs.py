"""Tests for the task-input shell-safety check (validate_inputs.py, ADR-0018)."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.env_sandbox import cwd, stderr

from .helpers import load_run_pipeline


class ValidateTaskTest(unittest.TestCase):
    """The check accepts the launcher's escaped forms and rejects raw
    forbidden characters and invalid backslash escapes."""

    def _check(self, task: str) -> tuple[bool, str]:
        mod = load_run_pipeline()
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, cwd(tmp):
            run_dir = Path(tmp) / ".specify" / "workflows" / "runs" / "r1"
            run_dir.mkdir(parents=True)
            (run_dir / "inputs.json").write_text(
                json.dumps({"inputs": {"task": task}}), encoding="utf-8"
            )
            with stderr(err), mock.patch("sys.exit", side_effect=SystemExit):
                try:
                    mod.validate_inputs.cmd_task("r1")
                except SystemExit:
                    return False, err.getvalue()
        return True, err.getvalue()

    def test_accepts_escaped_forms(self) -> None:
        ok, _ = self._check(r'a \$5 \"quoted\" \`tick\` C:\\dir')
        self.assertTrue(ok)

    def test_rejects_raw_quote(self) -> None:
        ok, _ = self._check('say "hi"')
        self.assertFalse(ok)

    def test_rejects_raw_dollar(self) -> None:
        ok, _ = self._check("cost $5")
        self.assertFalse(ok)

    def test_rejects_raw_backtick(self) -> None:
        ok, _ = self._check("use `ls`")
        self.assertFalse(ok)

    def test_rejects_invalid_backslash_escape(self) -> None:
        ok, _ = self._check(r"C:\dir")
        self.assertFalse(ok)
