"""Encrypted chat-history files, and the session store's class seam.

Bound, every file that holds chat text is an envelope (:mod:`.envelope`) under the
host's history key, with the file's slot as associated data:

* the state DB image (``state.db``) — written by :mod:`.session_db`; it carries the
  FTS index inside it, and no ``-wal`` / ``-shm`` / journal ever reaches the disk;
* transcript and dump files (``sessions/<id>.jsonl``, request dumps, trajectories,
  MoA traces) — :func:`append_record` (one envelope per line) or :func:`write_blob`.

A path outside the store root is refused. An envelope that fails to open (another
profile's key, a moved file, tampering) raises :class:`HistoryUnreadable` and is never
overwritten — a key mismatch must not destroy the other account's history.
Complete deletion is :func:`erase_history` plus the host dropping the key.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, List, Optional, Union

from agent_runtime.host_store import binding as _binding
from agent_runtime.host_store import envelope as _envelope
from agent_runtime.host_store.binding import HostStoreError

__layer__ = "stores"

PathLike = Union[str, "os.PathLike[str]"]
RECORD_PREFIX = "hsec1:"


class HistoryUnreadable(HostStoreError):
    """An encrypted history file this binding's key cannot open."""


def bound() -> bool:
    """A host store is bound AND it encrypts history (a credentials-only binding does not)."""
    current = _binding.current()
    return current is not None and current.encrypts_history


def _aad(current: _binding.HostStoreBinding, path: PathLike) -> bytes:
    return current.slot(path).encode("utf-8")


def seal_bytes(path: PathLike, data: bytes) -> bytes:
    current = _binding.require()
    return _envelope.seal(current.history_key(), data, aad=_aad(current, path))


def open_bytes(path: PathLike, blob: bytes) -> bytes:
    current = _binding.require()
    try:
        return _envelope.open_(current.history_key(), blob, aad=_aad(current, path))
    except _envelope.EnvelopeError as exc:
        raise HistoryUnreadable(f"{os.fspath(path)}: {exc}") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".hsec-tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_blob(path: PathLike, data: bytes) -> Path:
    """Replace *path* with one envelope of *data* (atomic)."""
    target = Path(os.path.abspath(os.fspath(path)))
    _atomic_write(target, seal_bytes(target, data))
    return target


def read_blob(path: PathLike) -> Optional[bytes]:
    """The plaintext of the envelope at *path*, or None when there is no file."""
    target = Path(os.path.abspath(os.fspath(path)))
    try:
        blob = target.read_bytes()
    except FileNotFoundError:
        return None
    return open_bytes(target, blob)


def append_record(path: PathLike, text: str) -> Path:
    """Append one encrypted record (its own envelope, one line) to *path*."""
    target = Path(os.path.abspath(os.fspath(path)))
    line = RECORD_PREFIX + base64.b64encode(seal_bytes(target, text.encode("utf-8"))).decode("ascii") + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="ascii") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return target


def append_json_records(path: PathLike, records: Iterable[Any]) -> Path:
    target = Path(os.path.abspath(os.fspath(path)))
    for record in records:
        append_record(target, json.dumps(record, ensure_ascii=False, default=str))
    return target


def read_records(path: PathLike) -> List[str]:
    target = Path(os.path.abspath(os.fspath(path)))
    out: List[str] = []
    with target.open("r", encoding="ascii") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if not line.startswith(RECORD_PREFIX):
                raise HistoryUnreadable(f"{target}: a plaintext line in an encrypted transcript")
            out.append(open_bytes(target, base64.b64decode(line[len(RECORD_PREFIX):])).decode("utf-8"))
    return out


def session_db_class(requested: type) -> type:
    """The class ``SessionDB()`` constructs: the encrypted store when bound, else *requested*."""
    if not bound():
        return requested
    from agent_runtime.host_store.session_db import encrypted_session_db_class

    return encrypted_session_db_class(requested)


def erase_history(home: PathLike, *, db_name: str = "state.db") -> List[Path]:
    """Delete every history file this profile wrote under *home*: the DB image and its temp
    files, and the ``sessions/`` transcripts and dumps. The DB must be closed. The host then
    drops the history key, so nothing that survived on flash can be opened again."""
    from agent_runtime.host_store.session_db import image_is_open

    root = Path(os.path.abspath(os.fspath(home)))
    db_path = root / db_name
    if image_is_open(db_path):
        raise HostStoreError(f"{db_path} is open; close every SessionDB before erasing history")
    removed: List[Path] = []
    candidates = [db_path, *root.glob(f".{db_name}.*.hsec-tmp")]
    sessions = root / "sessions"
    if sessions.is_dir():
        candidates.extend(p for p in sessions.rglob("*") if p.is_file())
    for path in candidates:
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed
