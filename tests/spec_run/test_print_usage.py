"""Unit tests for print_usage."""

import io
import tempfile
import unittest
from unittest import mock

from .helpers import load_spec_run


class PrintUsageTest(unittest.TestCase):
    def _load(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return load_spec_run(self.tmp.name)

    def test_print_usage_defaults_to_stdout(self):
        mod = self._load()
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            mod.print_usage()
        self.assertIn("Usage:", captured.getvalue())

    def test_print_usage_writes_to_given_stream(self):
        mod = self._load()
        err = io.StringIO()
        mod.print_usage(err)
        self.assertIn("Usage:", err.getvalue())
