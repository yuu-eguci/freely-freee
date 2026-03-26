"""Terminal input helpers for the interactive menu."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from app.errors import MenuCancelled, MenuEnvironmentError, MenuInputError

MenuKey = Literal["up", "down", "enter", "ignore"]


def ensure_menu_terminal() -> None:
    """Ensure stdin/stdout are attached to a TTY."""

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise MenuEnvironmentError(
            "Interactive menu requires TTY stdin/stdout. Please run in a terminal."
        )


@contextmanager
def raw_stdin_mode() -> Iterator[None]:
    """Temporarily switch stdin to raw mode."""

    try:
        import termios
        import tty
    except ImportError as exc:
        raise MenuEnvironmentError("Raw terminal input is not supported on this platform.") from exc

    try:
        stdin_fd = sys.stdin.fileno()
    except OSError as exc:
        raise MenuEnvironmentError("stdin file descriptor is not available.") from exc

    try:
        original_mode = termios.tcgetattr(stdin_fd)
    except termios.error as exc:
        raise MenuEnvironmentError("Failed to read terminal mode.") from exc

    try:
        tty.setraw(stdin_fd)
        yield
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, original_mode)


def read_menu_key() -> MenuKey:
    """Read one menu control key from stdin."""

    first = sys.stdin.buffer.read(1)
    if first == b"":
        raise MenuInputError("Reached EOF while waiting for menu input.")
    if first in (b"\r", b"\n"):
        return "enter"
    if first == b"\x03":
        raise MenuCancelled("Menu cancelled by user.")
    if first == b"\x04":
        raise MenuInputError("Received EOF (Ctrl+D) while waiting for menu input.")
    if first != b"\x1b":
        return "ignore"

    second = sys.stdin.buffer.read(1)
    if second == b"":
        raise MenuInputError("Incomplete escape sequence: missing second byte.")
    if second != b"[":
        return "ignore"

    third = sys.stdin.buffer.read(1)
    if third == b"":
        raise MenuInputError("Incomplete escape sequence: missing third byte.")
    if third == b"A":
        return "up"
    if third == b"B":
        return "down"
    return "ignore"
