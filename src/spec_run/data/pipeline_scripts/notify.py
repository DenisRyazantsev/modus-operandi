"""The victory.wav signal policy.

One responsibility: decide when and how to play the single victory.wav
signal (platform player selection, quiet degradation). Playback never
affects the exit code or the wrapper's output.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Absolute path of the victory.wav signal: shipped by the installer next to
# this module, so it is resolved from the module's own location at runtime.
SOUND_FILE = Path(__file__).resolve().parent / "victory.wav"


def notify() -> None:
    """Play the single victory.wav signal, for every event.

    Called when a human-gate menu opens (except the ADR revise feedback
    gate, which the wrapper answers itself and never signals), on a
    successful run and on a failed run alike — one sound for all events,
    never different signals. Playback is non-blocking (the player process is
    not waited for) and degrades quietly: no sound file, no system player or
    a non-TTY stdout simply skip the call, so the exit code and the
    wrapper's output are never affected.
    """
    try:
        if not getattr(sys.stdout, "isatty", lambda: False)():
            return
        if not SOUND_FILE.is_file():
            return
        if sys.platform == "darwin":
            player = shutil.which("afplay")
        elif sys.platform.startswith("win"):
            import winsound  # Windows only

            winsound.PlaySound(
                str(SOUND_FILE), winsound.SND_FILENAME | winsound.SND_ASYNC
            )
            return
        else:
            player = shutil.which("paplay") or shutil.which("aplay")
        if not player:
            return
        subprocess.Popen(
            [player, str(SOUND_FILE)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        # Quiet degradation: a sound problem must never fail the run.
        pass
