"""Unit tests for the sound-section validation in the run-pipeline wrapper."""

import io
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.env_sandbox import argv, cwd, stderr, stdin, stdout

from .helpers import FakeProc, load_run_pipeline, point_config_at


class SoundConfigTest(unittest.TestCase):
    """The wrapper validates the sound section before the run starts and
    refuses invalid settings with an explanation (ADR-0018)."""

    def _run_main(
        self, mod: Any, tmp: str, sound: dict[str, object] | None = None
    ) -> tuple[int, Any]:
        point_config_at(mod, tmp, sound=sound)
        with (
            cwd(tmp),
            mock.patch(
                "subprocess.Popen", return_value=FakeProc(["Run ID: abc12345"], 0)
            ) as popen,
            argv(["run-pipeline.py", "adr-pipeline"]),
            stdout(io.StringIO()),
            stdin(io.StringIO()),
        ):
            rc = mod.main()
        return rc, popen

    def test_invalid_enabled_type_aborts_before_run(self) -> None:
        mod = load_run_pipeline()
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, stderr(err):
            rc, popen = self._run_main(mod, tmp, sound={"is_sound_alert_enabled": "yes"})
        self.assertEqual(rc, 1)
        self.assertIn("sound.is_sound_alert_enabled must be a boolean", err.getvalue())
        popen.assert_not_called()

    def test_missing_sound_file_aborts_before_run(self) -> None:
        mod = load_run_pipeline()
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, stderr(err):
            rc, popen = self._run_main(mod, tmp, sound={"sound_file": "/nonexistent/x.wav"})
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", err.getvalue())
        popen.assert_not_called()

    def test_relative_sound_file_resolved_against_config_dir(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "my.wav").write_bytes(b"RIFF")
            rc, popen = self._run_main(mod, tmp, sound={"sound_file": "my.wav"})
        self.assertEqual(rc, 0)
        popen.assert_called_once()

    def test_relative_sound_file_plays_from_any_launch_dir(self) -> None:
        # Regression (bug review): a relative sound_file passes validation
        # against the config dir but used to be stored unresolved, so the
        # play-time existence check ran against the launch CWD and the alert
        # silently never played from any other directory (ADR-0018: behavior
        # must not depend on where the command is launched from).
        mod = load_run_pipeline()
        with (
            tempfile.TemporaryDirectory() as config_dir,
            tempfile.TemporaryDirectory() as run_dir,
        ):
            wav = Path(config_dir) / "my.wav"
            wav.write_bytes(b"RIFF")
            enabled, sound_file = mod.sound_settings(
                {"sound": {"is_sound_alert_enabled": True, "sound_file": "my.wav"}},
                Path(config_dir) / "config.yml",
            )
            self.assertEqual(Path(sound_file), wav.resolve())
            mod.configure_sound(enabled, sound_file)
            with (
                cwd(run_dir),
                mock.patch("sys.stdout.isatty", return_value=True),
                mock.patch("shutil.which", return_value="/usr/bin/paplay"),
                mock.patch("subprocess.Popen") as popen,
            ):
                mod.play_signal()
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0][-1], str(wav))

    def test_disabled_sound_allows_missing_file(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, popen = self._run_main(
                mod,
                tmp,
                sound={"is_sound_alert_enabled": False, "sound_file": "/nonexistent/x.wav"},
            )
        self.assertEqual(rc, 0)
        popen.assert_called_once()

    def test_default_sound_section_runs(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            rc, popen = self._run_main(mod, tmp, sound=None)
        self.assertEqual(rc, 0)
        popen.assert_called_once()
