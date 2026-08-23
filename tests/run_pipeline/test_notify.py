"""Unit tests for the victory.wav notification."""

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from .helpers import load_run_pipeline


class NotifyTest(unittest.TestCase):
    """One victory.wav for every event, played non-blockingly, with quiet
    degradation when the file, a system player or a TTY is unavailable."""

    def _sound(self, mod: types.ModuleType) -> Path:
        # SOUND_FILE resolves from the module's own location: ship the wav
        # next to the loaded copy.
        wav = Path(mod.__file__ or "").parent / "victory.wav"
        wav.write_bytes(b"RIFF")
        return wav

    def test_plays_sound_via_system_player(self) -> None:
        mod = load_run_pipeline()
        wav = self._sound(mod)
        with (
            mock.patch("sys.stdout.isatty", return_value=True),
            mock.patch("subprocess.Popen") as popen,
            mock.patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"),
        ):
            mod.play_signal()
        popen.assert_called_once()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[-1], str(wav))
        # The system player: afplay (macOS) or paplay/aplay (Linux).
        self.assertTrue(cmd[0].endswith(("afplay", "paplay", "aplay")))

    def test_skips_when_not_a_tty(self) -> None:
        mod = load_run_pipeline()
        with (
            mock.patch("sys.stdout.isatty", return_value=False),
            mock.patch("subprocess.Popen") as popen,
        ):
            mod.play_signal()
        popen.assert_not_called()

    def test_skips_when_sound_file_missing(self) -> None:
        # No victory.wav next to the wrapper: quiet degradation.
        mod = load_run_pipeline()
        with (
            mock.patch("sys.stdout.isatty", return_value=True),
            mock.patch("subprocess.Popen") as popen,
        ):
            mod.play_signal()
        popen.assert_not_called()

    def test_skips_when_no_player_available(self) -> None:
        mod = load_run_pipeline()
        self._sound(mod)
        with (
            mock.patch("sys.stdout.isatty", return_value=True),
            mock.patch("shutil.which", return_value=None),
            mock.patch("subprocess.Popen") as popen,
        ):
            mod.play_signal()
        popen.assert_not_called()

    def test_skips_when_disabled(self) -> None:
        mod = load_run_pipeline()
        mod.configure_sound(False)
        with (
            mock.patch("sys.stdout.isatty", return_value=True),
            mock.patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"),
            mock.patch("subprocess.Popen") as popen,
        ):
            mod.play_signal()
        popen.assert_not_called()

    def test_plays_custom_sound_file(self) -> None:
        mod = load_run_pipeline()
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "custom.wav"
            custom.write_bytes(b"RIFF")
            mod.configure_sound(True, str(custom))
            with (
                mock.patch("sys.stdout.isatty", return_value=True),
                mock.patch("shutil.which", return_value="/usr/bin/paplay"),
                mock.patch("subprocess.Popen") as popen,
            ):
                mod.play_signal()
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0][-1], str(custom))

    def test_empty_sound_file_means_shipped(self) -> None:
        mod = load_run_pipeline()
        mod.configure_sound(True, "")
        wav = self._sound(mod)
        with (
            mock.patch("sys.stdout.isatty", return_value=True),
            mock.patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"),
            mock.patch("subprocess.Popen") as popen,
        ):
            mod.play_signal()
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0][-1], str(wav))
