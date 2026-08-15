"""Unit tests for forward_terminal_input."""

import os
import pty
import threading
import time
import unittest

from .helpers import load_run_pipeline


class ForwardInputTest(unittest.TestCase):
    """forward_terminal_input copies terminal lines into the pty master and
    pauses while the feedback editor is open."""

    def _setup(self):
        read_fd, write_fd = os.pipe()
        master_fd, slave_fd = pty.openpty()
        # The text-mode file owns read_fd: it is closed via source.close()
        # (a GC of the file object closes the fd first, so os.close would
        # raise EBADF).
        source = os.fdopen(read_fd, "r")
        return source, write_fd, master_fd, slave_fd

    def _read_echo(self, master_fd, expected_bytes, timeout=2.0):
        # The pty line discipline echoes with \n translated to \r\n (ONLCR);
        # strip \r before comparing.
        deadline = time.monotonic() + timeout
        data = b""
        while time.monotonic() < deadline and len(data) < len(expected_bytes):
            try:
                data += os.read(master_fd, 16)
            except BlockingIOError:
                time.sleep(0.05)
        return data.replace(b"\r", b"")

    def test_forwards_terminal_lines_into_pty(self):
        mod = load_run_pipeline()
        source, write_fd, master_fd, slave_fd = self._setup()
        try:
            stop = threading.Event()
            thread = threading.Thread(
                target=mod.forward_terminal_input,
                args=(source, master_fd, threading.Event(), stop),
                daemon=True,
            )
            thread.start()
            os.write(write_fd, b"2\n")
            # The pty line discipline echoes the forwarded line back: reading
            # the master proves the wrapper forwarded it into specify's stdin.
            self.assertEqual(self._read_echo(master_fd, b"2\n"), b"2\n")
            stop.set()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
        finally:
            source.close()
            os.close(write_fd)
            os.close(master_fd)
            os.close(slave_fd)

    def test_paused_while_editor_open(self):
        mod = load_run_pipeline()
        source, write_fd, master_fd, slave_fd = self._setup()
        try:
            pause = threading.Event()
            pause.set()
            stop = threading.Event()
            thread = threading.Thread(
                target=mod.forward_terminal_input,
                args=(source, master_fd, pause, stop),
                daemon=True,
            )
            thread.start()
            os.write(write_fd, b"2\n")
            os.set_blocking(master_fd, False)
            with self.assertRaises(BlockingIOError):
                os.read(master_fd, 16)
            pause.clear()
            # After the editor closes the pending line is forwarded.
            self.assertEqual(self._read_echo(master_fd, b"2\n"), b"2\n")
            stop.set()
            thread.join(timeout=1)
        finally:
            os.set_blocking(master_fd, True)
            source.close()
            os.close(write_fd)
            os.close(master_fd)
            os.close(slave_fd)
