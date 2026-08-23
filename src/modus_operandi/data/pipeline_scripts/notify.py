"""The victory.wav signal policy.

One responsibility: decide when and how to play the single victory.wav
signal (platform player selection, quiet degradation). Playback never
affects the exit code or the wrapper's output. The signal can be disabled
or replaced with a custom sound file through the `sound:` section of the
installed config.yml (ADR-0018).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Absolute path of the victory.wav signal: shipped by the installer next to
# this module, so it is resolved from the module's own location at runtime.
SOUND_FILE = Path(__file__).resolve().parent / "victory.wav"

# Runtime state, set by the wrapper from config.yml (configure_sound); the
# defaults match the old behavior: enabled + the shipped victory.wav.
_enabled = True
_sound_file: Path = SOUND_FILE


def configure_sound(enabled: bool, sound_file: str | Path = "") -> None:
    """Set the alert policy from the runtime config (called once by the wrapper).

    An empty sound_file means the shipped victory.wav.
    """
    global _enabled, _sound_file
    _enabled = enabled
    _sound_file = Path(sound_file) if sound_file else SOUND_FILE


def play_signal() -> None:
    """Play the single victory.wav signal, for every event.

    Called when a human-gate menu opens (except the feedback gate, which
    the wrapper answers itself and never signals), on a
    successful run and on a failed run alike — one sound for all events,
    never different signals. Playback is non-blocking (the player process is
    not waited for) and degrades quietly: no sound file, no system player or
    a non-TTY stdout simply skip the call, so the exit code and the
    wrapper's output are never affected.
    """
    if not _enabled:
        return
    try:
        if not getattr(sys.stdout, "isatty", lambda: False)():
            return
        if not _sound_file.is_file():
            return
        if sys.platform == "darwin":
            player = shutil.which("afplay")
        elif sys.platform.startswith("win"):
            import winsound  # Windows only

            winsound.PlaySound(str(_sound_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        else:
            player = shutil.which("paplay") or shutil.which("aplay")
        if not player:
            return
        subprocess.Popen(
            [player, str(_sound_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        # Quiet degradation: a sound problem must never fail the run.
        pass
