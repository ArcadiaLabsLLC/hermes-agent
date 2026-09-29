"""Sealed file logs: with a host store bound, every log line is an encrypted record.

Hermes's file logs (``hermes_logging``: ``agent.log``, ``errors.log``, ``gateway.log``,
``gui.log``) can carry chat text and provider diagnostics — ``agent.log`` records each
turn's opening words at INFO. On a phone nothing holding chat text may reach the disk in
plaintext, so while a host store is bound ``hermes_logging``'s one handler factory
(``_new_file_handler``) builds :class:`SealedRotatingFileHandler` instead: upstream's
rotating handler with its stream swapped for one that appends each formatted line as one
:func:`~agent_runtime.host_store.history.append_record` envelope (the history key, the
log file's slot as associated data). Rotation, levels, filters and the redacting formatter
are the stdlib's and Hermes's own. Unbound — every desktop Hermes — nothing here runs.

Read a sealed log back with :func:`~agent_runtime.host_store.history.read_records`.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from agent_runtime.host_store import binding as _binding
from agent_runtime.host_store import history as _history

__layer__ = "stores"

__all__ = ["SealedLogStream", "SealedRotatingFileHandler", "bound", "sealed_file_handler"]


def bound() -> bool:
    return _binding.bound()


class SealedLogStream:
    """The file-like object the handler writes to: one ``write`` is one encrypted record."""

    def __init__(self, path: "os.PathLike[str] | str") -> None:
        self.path = Path(os.path.abspath(os.fspath(path)))

    def write(self, text: str) -> int:
        line = text[:-1] if text.endswith("\n") else text
        if line:
            _history.append_record(self.path, line)
        return len(text)

    def tell(self) -> int:
        """The sealed file's size: what ``RotatingFileHandler.shouldRollover`` compares."""
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def seek(self, _offset: int, _whence: int = 0) -> int:
        return self.tell()

    def flush(self) -> None:
        return None  # append_record fsyncs each record

    def close(self) -> None:
        return None


class SealedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """``RotatingFileHandler`` whose stream is a :class:`SealedLogStream` (opened lazily)."""

    def __init__(self, path: "os.PathLike[str] | str", *, max_bytes: int, backup_count: int) -> None:
        super().__init__(os.fspath(path), maxBytes=max_bytes, backupCount=backup_count,
                         encoding="utf-8", delay=True)
        # hermes_logging's idempotency check keys a queued handler by this path.
        self._hermes_routed_log_path = Path(self.baseFilename).resolve()

    def _open(self) -> SealedLogStream:  # type: ignore[override]
        return SealedLogStream(self.baseFilename)


def sealed_file_handler(path: "os.PathLike[str] | str", *, level: int, max_bytes: int, backup_count: int,
                        formatter: logging.Formatter) -> SealedRotatingFileHandler:
    handler = SealedRotatingFileHandler(path, max_bytes=max_bytes, backup_count=backup_count)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler
