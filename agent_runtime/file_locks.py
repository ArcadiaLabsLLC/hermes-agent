"""Exclusive, non-blocking byte-0 file locks on an open handle (program rule 15).

One owner for the platform split (``msvcrt.locking`` on Windows, ``flock``
elsewhere) that ``serve_socket``'s owner lock carried as ``_lock_first_byte`` /
``_unlock_first_byte``. Program §4 names the other copies that fold here in
their own lanes (``mission_chat_turns._lock_fd_*`` folded onto the handle pair
in lane 2B-B).

``try_lock_fd`` / ``unlock_fd`` are the FILE-DESCRIPTOR pair, moved whole from
``persona_chat_continuity._try_lock/_unlock`` (lane B3): no padding, no errno
translation — they raise the raw ``OSError`` the chat-root lease reads as
"held". A stdlib-only leaf.
"""

from __future__ import annotations

import errno
import os

if os.name == "nt":  # pragma: no cover - platform split, both sides exercised in CI
    import msvcrt
else:  # pragma: no cover - platform split
    import fcntl

__layer__ = "models"

__all__ = ["LockUnavailable", "try_lock_exclusive", "try_lock_fd", "unlock", "unlock_fd"]


class LockUnavailable(Exception):
    """Another holder has the lock; a caller may retry. Every other ``OSError`` is not this."""


def try_lock_exclusive(handle) -> None:
    """Exclusive, NON-BLOCKING lock on byte 0 — the locks.py pattern.

    The file is padded to one byte first because ``msvcrt.locking`` cannot lock
    a region of an empty file.
    """

    if os.name == "nt":
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EDEADLK, 13, 36}:
                raise LockUnavailable() from exc
            raise
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
            raise LockUnavailable() from exc
        raise


def unlock(handle) -> None:
    """Release the byte-0 lock :func:`try_lock_exclusive` took."""

    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def try_lock_fd(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_fd(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
