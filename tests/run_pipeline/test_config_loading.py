"""Unit tests for the runtime config loading (config_invocation.load_config).

A config that exists but cannot be read or parsed must abort the run with a
clear error, not silently degrade to the opencode defaults: the silent
degrade made `backend: cursor` invisible (the run used opencode) and
exported empty role models (run-agent-cursor.sh failed for reviewer-srp and
the other roles). A missing config still degrades to the defaults, and the
editor-saved encodings (UTF-16 with/without BOM) parse instead of failing.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.env_sandbox import argv, cwd, stdin, stdout

from .helpers import FakeProc, load_run_pipeline

FRESH_YAML = """\
backend: cursor
cursor:
  models:
    planner:
      model: composer-2
    executor:
      model: composer-2
workflow: {}
"""


class LoadConfigTest(unittest.TestCase):
    """load_config: missing degrades, existing-but-broken raises ValueError."""

    def _write(self, tmp: str, payload: bytes) -> Path:
        path = Path(tmp) / "config.yml"
        path.write_bytes(payload)
        return path

    def test_missing_file_degrades_to_defaults(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = mod.load_config(Path(tmp) / "does-not-exist.yml")
        self.assertEqual(cfg, {})

    def test_invalid_yaml_raises_value_error(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, b"backend: [unclosed\n")
            with self.assertRaises(ValueError) as cm:
                mod.load_config(path)
        self.assertIn("invalid config.yml", str(cm.exception))

    def test_non_mapping_root_raises_value_error(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, b"42\n")
            with self.assertRaises(ValueError) as cm:
                mod.load_config(path)
        self.assertIn("top-level must be a mapping", str(cm.exception))

    def test_editor_encodings_parse(self) -> None:
        # A macOS text editor can save the config as UTF-16 (TextEdit offers
        # "UTF-16" in Save As), with or without BOM: both must parse and
        # deliver the cursor backend instead of failing deep in the pipeline.
        mod = load_run_pipeline()
        for encoding in ("utf-16", "utf-16-le"):
            with self.subTest(encoding=encoding):
                with tempfile.TemporaryDirectory() as tmp:
                    path = self._write(tmp, FRESH_YAML.encode(encoding))
                    cfg = mod.load_config(path)
                self.assertEqual(cfg["backend"], "cursor")
                self.assertEqual(mod.role_model(cfg, "cursor", "planner"), "composer-2")


class MainBrokenConfigTest(unittest.TestCase):
    """main() aborts with a clear error on an existing-but-broken config."""

    def test_main_fails_fast_on_unparseable_config(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_bytes(b"backend: [unclosed\n")
            mod.CONFIG_PATH = path
            captured: dict[str, object] = {}

            def fake_popen(*a: object, **kw: object) -> FakeProc:
                captured["spawned"] = True
                return FakeProc([], 0, **kw)

            with (
                cwd(tmp),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                argv(["run-pipeline.py", "adr-pipeline"]),
                stdout(io.StringIO()),
                stdin(io.StringIO()),
                mock.patch("sys.stderr", io.StringIO()) as stderr,
            ):
                rc = mod.main()
        self.assertEqual(rc, 1)
        self.assertNotIn("spawned", captured)
        self.assertIn("invalid config.yml", stderr.getvalue())

    def test_main_runs_with_utf16_config(self) -> None:
        # Regression: a UTF-16-saved config used to crash the wrapper with a
        # raw UnicodeDecodeError; it must parse and run normally.
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_bytes(FRESH_YAML.encode("utf-16"))
            mod.CONFIG_PATH = path
            captured: dict[str, object] = {}

            def fake_popen(*a: object, **kw: object) -> FakeProc:
                captured["env"] = kw.get("env", {})
                return FakeProc(["Run ID: abc12345"], 0, **kw)

            with (
                cwd(tmp),
                mock.patch("subprocess.Popen", side_effect=fake_popen),
                argv(["run-pipeline.py", "adr-pipeline"]),
                stdout(io.StringIO()),
                stdin(io.StringIO()),
            ):
                rc = mod.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured["env"]["MO_BACKEND"], "cursor")
        self.assertEqual(captured["env"]["MO_PLANNER_MODEL"], "composer-2")


if __name__ == "__main__":
    unittest.main()
