"""pty/terminal plumbing for the run-pipeline.py wrapper.

One responsibility: open the pty, disable its echo, spawn specify on the
slave end and forward terminal input into the master end in the background,
and release the pty again (stop_forwarding). run_pipeline.py only consumes
the returned handles.
"""

from __future__ import annotations

import contextlib
import os
import pty
import select
import subprocess
import sys
import termios
import threading
import time
from typing import TextIO


def forward_terminal_input(
    source: TextIO, master_fd: int, pause: threading.Event, stop: threading.Event
) -> None:
    """Forward terminal input to specify's pty stdin.

    Runs in a background thread while specify runs; the main thread pauses
    it (pause.set()) while the feedback editor is open so the user's
    keystrokes reach only the editor. Exits on terminal EOF or when stop is
    set.

    The source is read as raw bytes on its fd, never through a blocking
    readline(): a line read would sit blocked mid-line once a partial line
    was typed, ignoring pause/stop until the next completed line — the
    forwarding thread would then swallow keystrokes the user typed into
    the feedback editor and forward them to the pty, where the gate's
    input() could read them as an unintended answer. Chunks are forwarded
    as they arrive; the pty line discipline buffers them until the
    newline, so the gate still reads whole lines.
    """
    try:
        fd = source.fileno()
    except (OSError, ValueError):
        return
    while not stop.is_set():
        if pause.is_set():
            time.sleep(0.05)
            continue
        try:
            readable, _, _ = select.select([fd], [], [], 0.1)
        except (OSError, ValueError):
            return
        if not readable:
            continue
        try:
            chunk = os.read(fd, 4096)
        except (OSError, ValueError):
            return
        if not chunk:
            return  # terminal EOF: nothing more to forward
        try:
            os.write(master_fd, chunk)
        except (OSError, ValueError):
            return


def stop_forwarding(
    master_fd: int | None,
    forward_stop: threading.Event,
    forward_thread: threading.Thread | None,
) -> None:
    """Stop stdin forwarding and release the pty before reaping the child.

    The forward thread would otherwise keep writing into the pty while the
    wrapper exits, so it is stopped and joined first; the master fd is
    closed best-effort (a pty-less non-TTY run passes None for both).
    """
    forward_stop.set()
    if master_fd is not None:
        assert forward_thread is not None
        forward_thread.join(timeout=1)
        with contextlib.suppress(OSError):
            os.close(master_fd)


def set_pty_no_echo(fd: int) -> None:
    """Disable ECHO on the pty slave (best effort).

    The user already sees their keystrokes echoed by the real terminal; a
    pty-side ECHO would only accumulate echoed bytes in the master's read
    buffer. termios failure leaves the pty at its defaults.
    """
    try:
        attrs = termios.tcgetattr(fd)
        # tcgetattr returns a 7-element list; index 3 is the local-flags
        # field (lflag), where ECHO/ECHONL live — clearing them there stops
        # the pty from echoing, without touching the other modes.
        attrs[3] &= ~(termios.ECHO | termios.ECHONL)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (OSError, ValueError):
        pass


def spawn_specify(
    specify_cmd: list[str], env: dict[str, str]
) -> tuple[
    subprocess.Popen[str], int | None, threading.Event, threading.Event, threading.Thread | None
]:
    """Spawn specify and own its stdin plumbing; returns the live run parts.

    The wrapper owns specify's stdin only on a terminal run: a pty keeps
    sys.stdin.isatty() True inside specify (its gate step goes PAUSED on a
    non-TTY stdin, see ADR-0002), so interactive gates prompt as before
    while the wrapper can still inject the feedback-gate answer itself. On a
    non-TTY run specify keeps the inherited stdin (also non-TTY), so gates
    go PAUSED and no "┌─ Gate" menu is drawn — exactly the documented
    non-interactive behavior.

    Returns (proc, master_fd, forward_pause, forward_stop, forward_thread);
    on a non-TTY run master_fd and forward_thread are None.
    """
    master_fd: int | None = None
    forward_pause = threading.Event()
    forward_stop = threading.Event()
    forward_thread: threading.Thread | None = None
    if sys.stdin.isatty():
        master_fd, slave_fd = pty.openpty()
        set_pty_no_echo(slave_fd)
        proc = subprocess.Popen(
            specify_cmd,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        os.close(slave_fd)
        forward_thread = threading.Thread(
            target=forward_terminal_input,
            args=(sys.stdin, master_fd, forward_pause, forward_stop),
            daemon=True,
        )
        forward_thread.start()
    else:
        proc = subprocess.Popen(
            specify_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    return proc, master_fd, forward_pause, forward_stop, forward_thread
