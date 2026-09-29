"""The one session store over an encrypted image — ``SessionDB`` with its storage moved, not copied.

Bound, ``SessionDB()`` constructs :class:`EncryptedSessionDB` (the class seam in
``hermes_state.SessionDB.__new__``). It is the same class — same schema, same mixins,
same FTS5 index, same write path — with only the storage layer overridden:

* the live database is a named in-process ``memdb`` image, shared by every handle on
  the same path in this process (SQLite's own locking arbitrates them), so its journal
  never reaches the disk: there is no ``-wal``, no ``-shm``, no rollback journal file;
* after every committed ``_execute_write``, and at open and close, the image is
  serialized, sealed (:mod:`.envelope`, the host's history key, the file's slot as
  associated data) and atomically replaces ``state.db``;
* ``PRAGMA secure_delete`` zeroes freed pages, so a deleted session is gone from the
  next sealed image, not merely unlinked from the B-tree.

The file-identity probes the desktop store runs against a live SQLite file (inode,
header, WAL generation) do not apply to a sealed image and are answered locally.
One process only: the phone runs Hermes in-process, so there is no second writer to
arbitrate on disk. Cost: each persisted write re-seals the whole image — linear in
the database size (measured ~0.2 s at 10 MB on a desktop core).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Optional

from agent_runtime.host_store import binding as _binding
from agent_runtime.host_store import history as _history
from agent_runtime.host_store.binding import HostStoreError

__layer__ = "stores"

logger = logging.getLogger(__name__)

_IMAGES_LOCK = threading.Lock()
_IMAGES: Dict[str, "_Image"] = {}
_CLASSES: Dict[type, type] = {}


def _canonical(path: "os.PathLike[str] | str") -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


class _Image:
    """One encrypted database image: a named memdb anchored by one connection, sealed to *path*."""

    def __init__(self, path: Path):
        current = _binding.current()
        if current is None:
            raise HostStoreError("no host store is bound")
        slot = current.slot(path)  # raises OutsideStoreRoot
        self.path = path
        self.refs = 0
        self._seal_lock = threading.Lock()
        digest = hashlib.sha256(f"{os.getpid()}|{slot}|{id(self)}".encode("utf-8")).hexdigest()[:32]
        self.uri = f"file:/hsec-{digest}?vfs=memdb"
        plaintext = _history.read_blob(path)  # HistoryUnreadable on another key: never overwritten
        self.anchor = sqlite3.connect(self.uri, uri=True, check_same_thread=False, isolation_level=None, timeout=30.0)
        try:
            if plaintext:
                staging = sqlite3.connect(":memory:")
                try:
                    staging.deserialize(plaintext)
                    staging.backup(self.anchor)
                finally:
                    staging.close()
            self.anchor.execute("PRAGMA secure_delete=ON")
        except BaseException:
            self.anchor.close()
            raise

    def connect(self, *, read_only: bool, timeout: float) -> sqlite3.Connection:
        conn = sqlite3.connect(self.uri, uri=True, check_same_thread=False, timeout=timeout, isolation_level=None)
        conn.execute("PRAGMA secure_delete=ON")
        if read_only:
            conn.execute("PRAGMA query_only=ON")
        return conn

    def seal(self) -> None:
        """Serialize the committed image under a read transaction and replace ``state.db``."""
        with self._seal_lock:
            self.anchor.execute("BEGIN")
            try:
                self.anchor.execute("SELECT count(*) FROM sqlite_master").fetchone()
                image = self.anchor.serialize()
            finally:
                self.anchor.execute("COMMIT")
            _history.write_blob(self.path, image)

    def close(self) -> None:
        try:
            self.seal()
        finally:
            self.anchor.close()


def _acquire_image(path: Path) -> _Image:
    key = _canonical(path)
    with _IMAGES_LOCK:
        image = _IMAGES.get(key)
        if image is None:
            image = _IMAGES[key] = _Image(Path(os.path.abspath(os.fspath(path))))
        image.refs += 1
        return image


def _release_image(image: _Image) -> None:
    key = _canonical(image.path)
    with _IMAGES_LOCK:
        image.refs -= 1
        if image.refs > 0:
            return
        _IMAGES.pop(key, None)
    image.close()


def image_is_open(path: "os.PathLike[str] | str") -> bool:
    with _IMAGES_LOCK:
        return _canonical(path) in _IMAGES


def encrypted_session_db_class(base: type) -> type:
    """``EncryptedSessionDB`` over *base* (``hermes_state.SessionDB``), built once per base."""
    cached = _CLASSES.get(base)
    if cached is not None:
        return cached
    from hermes_state_fts import load_fts5_cjk_extension
    from hermes_state_wal import apply_database_pragmas

    class EncryptedSessionDB(base):  # type: ignore[misc, valid-type]
        """``SessionDB`` whose storage is an encrypted image (module docstring)."""

        _hsec_image: Optional[_Image] = None

        def __init__(self, *args, **kwargs):
            try:
                super().__init__(*args, **kwargs)
            except BaseException:
                image, self._hsec_image = self._hsec_image, None
                if image is not None:
                    _release_image(image)
                raise

        def _hsec_attach(self) -> _Image:
            if self._hsec_image is None:
                self._hsec_image = _acquire_image(Path(self.db_path))
            return self._hsec_image

        def _open_writer(self) -> None:
            self._hsec_attach()
            self._conn = self._open_writer_conn()
            self._init_schema()
            self._ensure_db_file_generation()
            self._hsec_image.seal()

        def _open_writer_conn(self) -> sqlite3.Connection:
            conn = self._hsec_attach().connect(read_only=False, timeout=1.0)
            try:
                conn.row_factory = sqlite3.Row
                self._wal_active = False  # memdb: journal in memory, reads share the writer lock
                apply_database_pragmas(conn, db_label="state.db")
                conn.execute("PRAGMA foreign_keys=ON")
                self._fts_cjk_loaded = load_fts5_cjk_extension(conn)
            except BaseException:
                conn.close()
                raise
            return conn

        def _open_read_only(self) -> None:
            if not Path(self.db_path).is_file():
                raise sqlite3.OperationalError(f"unable to open database file: {self.db_path}")
            self._conn = self._connect_read_only(timeout=5.0)
            cursor = self._conn.cursor()
            self._fts_enabled = self._fts_table_probe(cursor, "messages_fts") is True
            if self._fts_enabled:
                self._trigram_available = self._fts_table_probe(cursor, "messages_fts_trigram") is True

        def _connect_read_only(self, timeout: float) -> sqlite3.Connection:
            conn = self._hsec_attach().connect(read_only=True, timeout=timeout)
            conn.row_factory = sqlite3.Row
            return conn

        # A sealed image has no inode/header/WAL generation to probe.
        def _record_db_file_identity(self) -> None:
            self._db_file_identity = None
            self._db_sidecar_identity = {}

        def _db_file_was_replaced(self) -> bool:
            return False

        def _wal_generation_was_lost(self) -> bool:
            return False

        def _try_wal_checkpoint(self) -> None:
            if self._hsec_image is not None and not self.read_only:
                self._hsec_image.seal()

        def _execute_write(self, fn, patience_s=None):
            result = super()._execute_write(fn, patience_s=patience_s)
            self._hsec_image.seal()
            return result

        def flush_history(self) -> None:
            """Seal the image now (the write path already does after every commit)."""
            if self._hsec_image is not None and not self.read_only:
                self._hsec_image.seal()

        def close(self):
            if self._shared_registry_owned:
                return super().close()
            try:
                super().close()
            finally:
                image, self._hsec_image = self._hsec_image, None
                if image is not None:
                    _release_image(image)

    EncryptedSessionDB.__qualname__ = EncryptedSessionDB.__name__ = "EncryptedSessionDB"
    _CLASSES[base] = EncryptedSessionDB
    return EncryptedSessionDB
