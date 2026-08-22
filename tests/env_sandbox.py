"""Environment sandboxing helpers: real os.environ / os.chdir / sys.argv.

These replace mock.patch.dict / mock.patch.object(Path, "cwd") /
mock.patch.object(sys, "argv"): the values are real, only the host
environment is saved and restored around each use. A test that changes the
working directory, the environment or the argv still runs against real
files, real subprocesses and the real entry point.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def env(overrides: dict[str, str] | None = None, clear: bool = False) -> Iterator[Any]:
    """Set environment variables for the block, restoring the old ones after.

    With clear=True the environment starts empty (only the overrides are
    set); otherwise the host environment is kept and patched.
    """
    import os

    old = os.environ.copy()
    try:
        if clear:
            os.environ.clear()
        if overrides:
            os.environ.update(overrides)
        yield os.environ
    finally:
        os.environ.clear()
        os.environ.update(old)


@contextmanager
def cwd(path: str | Path) -> Iterator[None]:
    """Change the working directory for the block, restoring the old one."""
    import os

    old = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


@contextmanager
def argv(args: list[str]) -> Iterator[None]:
    """Replace sys.argv for the block, restoring the old one."""
    import sys

    old = sys.argv
    try:
        sys.argv = args
        yield
    finally:
        sys.argv = old


@contextmanager
def stderr(sink: Any) -> Iterator[Any]:
    """Point sys.stderr at a real file-like object for the block."""
    import sys

    old = sys.stderr
    try:
        sys.stderr = sink
        yield sink
    finally:
        sys.stderr = old


@contextmanager
def stdout(sink: Any) -> Iterator[Any]:
    """Point sys.stdout at a real file-like object for the block."""
    import sys

    old = sys.stdout
    try:
        sys.stdout = sink
        yield sink
    finally:
        sys.stdout = old


@contextmanager
def stdin(sink: Any) -> Iterator[Any]:
    """Point sys.stdin at a real file-like object for the block."""
    import sys

    old = sys.stdin
    try:
        sys.stdin = sink
        yield sink
    finally:
        sys.stdin = old
