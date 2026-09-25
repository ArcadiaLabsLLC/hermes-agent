"""The turn store on disk: one file per chat session, its lock, its bounds.

Layout constants and every path; the per-session cross-process lock (yields
``acquired: bool`` — a chat turn never hangs on a stuck lock); read / write /
archive of one session file; the per-session turn cap; the session-file GC; the
one-time monolith migration. ``journal._mutate_session`` is the only writer
that calls in from above.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from agent_runtime import paths
from agent_runtime.file_locks import LockUnavailable, try_lock_exclusive, unlock
from agent_runtime.serde import safe_assignment_text

from agent_runtime.mission_chat_turns.states import INFLIGHT_TURN_STATES, _record_state

__layer__ = "stores"


# ---------------------------------------------------------------------------
# Storage layout (one file per chat session)
# ---------------------------------------------------------------------------
# Each chat session owns exactly one file
#   ``mission_chat_turns/<safe_session_key>.json``
# holding that session's ``{client_message_id: record}`` map, plus a co-located
# per-session lock ``mission_chat_turns/<safe_session_key>.lock``. Concurrent
# turns in DIFFERENT chats never contend (they touch different files/locks);
# same-session concurrency keeps today's exclusive read-modify-write semantics.
# This retires the old single ``mission_chat_turns.json`` monolith, whose every
# incremental flush rewrote the WHOLE store under one global lock — the store
# now aligns with the per-actor "the store IS the checkpoint" model (operator
# ruling 2026-07-17: "one file per chat is a good method for storage").
_STORE_DIR_NAME = "mission_chat_turns"
_ARCHIVE_DIR_NAME = "mission_chat_turns_archive"
# Legacy monolith. Split ONCE into per-session files on first read/write that
# finds it, then renamed aside (kept, never deleted).
_LEGACY_STORE_NAME = "mission_chat_turns.json"
_LEGACY_MIGRATED_NAME = "mission_chat_turns.legacy.json"
_MIGRATE_LOCK_NAME = "mission_chat_turns.migrate.lock"
_GC_LOCK_NAME = "mission_chat_turns.gc.lock"
_SESSION_FILE_SUFFIX = ".json"
_SESSION_LOCK_SUFFIX = ".lock"
# Filename scheme: a sanitized, human-readable prefix of the session key plus a
# sha256 suffix so long/odd session ids stay filesystem-safe AND collision-free
# (two keys with the same sanitized prefix still get distinct files). 80 + 1 +
# 12 + 5 (".json") = 98 chars keeps us well under the Windows MAX_PATH budget
# for any sane runtime root.
_SESSION_KEY_PREFIX_MAX = 80
_SESSION_KEY_HASH_LEN = 12

_LOCK_TIMEOUT_SECONDS = 2.0
_LOCK_POLL_SECONDS = 0.01
# Migration is a one-time, bounded split — wait comfortably for whichever
# process is doing it rather than racing a partial layout.
_MIGRATE_LOCK_TIMEOUT_SECONDS = 10.0
# The max-sessions GC is opportunistic (retention "can transiently exceed its
# bound rather than lose live state"), so both its own lock and the per-file
# probes it takes are short/non-blocking — a busy session is simply skipped and
# retried on the next new-session write.
_GC_LOCK_TIMEOUT_SECONDS = 1.0


# Retention bounds, applied on every write inside the per-session lock (turn
# cap) and after each new-session-file creation (session-file GC). The
# per-session bound must stay comfortably above the projection's displayable
# message tail (MAX_PERSONA_CHAT_MESSAGE_TAIL = 40 in persona_chat_history.py)
# so no displayable agent row loses turn_elements.
_RETENTION_MAX_TURNS_PER_SESSION = 100
_RETENTION_MAX_SESSIONS = 50


def _apply_session_turn_cap(
    session: dict[str, Any],
    *,
    protected_message: str | None = None,
) -> None:
    """Per-session tail bound, applied in place inside the session lock.

    Keep the ``_RETENTION_MAX_TURNS_PER_SESSION`` most recent records by
    ``updated_at``. ``running`` records are never evicted (a live turn must not
    lose its write-ahead marker) and neither is the record being written, so a
    session can transiently exceed its bound rather than lose live state.
    """

    excess = len(session) - _RETENTION_MAX_TURNS_PER_SESSION
    if excess <= 0:
        return
    evictable = sorted(
        (
            str(record.get("updated_at") or "") if isinstance(record, dict) else "",
            str(message_key),
        )
        for message_key, record in session.items()
        if not (
            str(message_key) == str(protected_message)
            or _record_state(record) in INFLIGHT_TURN_STATES
        )
    )
    for _, message_key in evictable[:excess]:
        session.pop(message_key, None)


def _gc_session_files(*, protected_session_key: str | None = None) -> None:
    """Bound the number of session FILES on disk (archive-never-delete).

    When ``mission_chat_turns/`` exceeds ``_RETENTION_MAX_SESSIONS`` live files,
    move the oldest-updated session files under ``mission_chat_turns_archive/``.
    Never archives the protected session (the one just written) nor any file
    holding a ``running`` record (a live concurrent turn). Best-effort by
    design: it runs under its own GC lock and probes each candidate's session
    lock non-blocking, so it can never deadlock against a live write and simply
    skips (and retries on the next new-session write) whatever it cannot safely
    claim. Any failure is swallowed — retention is invisible to the caller.
    """

    try:
        if len(_iter_session_files()) <= _RETENTION_MAX_SESSIONS:
            return
        protected_path = (
            _session_file_path(protected_session_key) if protected_session_key else None
        )
        with try_session_lock(_gc_lock_path(), timeout_seconds=_GC_LOCK_TIMEOUT_SECONDS) as acquired:
            if not acquired:
                return
            files = _iter_session_files()
            excess = len(files) - _RETENTION_MAX_SESSIONS
            if excess <= 0:
                return
            dropped = 0
            for path in sorted(files, key=lambda item: (_session_file_recency(item), item.name)):
                if dropped >= excess:
                    break
                if protected_path is not None and path == protected_path:
                    continue
                if _archive_if_idle(path):
                    dropped += 1
    except Exception:
        return


def _archive_if_idle(path: Path) -> bool:
    """Archive one GC candidate unless it is busy: its session lock is probed
    NON-blocking (a live write simply wins), and a file holding an in-flight
    record is never archived. ``True`` only when the file moved."""

    with try_session_lock(_lock_path_for_session_file(path), timeout_seconds=0.0) as got:
        if not got:
            return False
        session = _read_session_map(path)
        if any(_record_state(record) in INFLIGHT_TURN_STATES for record in session.values()):
            return False
        return _archive_session_file(path)


def _migrate_legacy_if_present() -> None:
    """Split the legacy monolith into per-session files ONCE, crash-safely.

    A single stat fast-paths the common case (no monolith). When the monolith
    exists, the split runs under a global migration lock so two processes never
    race it. For each legacy session, a per-session file is written ONLY when it
    does not already exist — so a per-session file written by a live turn (or by
    a partially-completed prior migration) is authoritative and never clobbered.
    The monolith is then renamed aside (kept, not deleted). This is idempotent
    and converges from a half-migrated state: a re-run skips the files already
    split, writes the rest, and completes the rename.
    """

    legacy = _legacy_store_path()
    try:
        if not legacy.exists():
            return
    except OSError:
        return
    with try_session_lock(_migrate_lock_path(), timeout_seconds=_MIGRATE_LOCK_TIMEOUT_SECONDS) as acquired:
        if not acquired:
            return
        try:
            if not legacy.exists():
                return
        except OSError:
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if isinstance(data, dict):
            _store_dir().mkdir(parents=True, exist_ok=True)
            for raw_session_key, session_map in data.items():
                if not isinstance(session_map, dict):
                    continue
                session_key = safe_assignment_text(raw_session_key, limit=240)
                if not session_key:
                    continue
                target = _session_file_path(session_key)
                if target.exists():
                    # Authoritative per-session file already present (live write
                    # or a prior partial migration) — never clobber it.
                    continue
                _write_session_file(target, session_map)
        # Rename the monolith aside even if it was unreadable, so migration
        # always converges instead of re-attempting a corrupt file forever.
        try:
            os.replace(str(legacy), str(_migrated_legacy_path()))
        except OSError:
            pass
    # A legacy store could carry more sessions than the current bound; enforce
    # it once after the split (best-effort, nothing is live under the migration
    # lock we just released).
    _gc_session_files(protected_session_key=None)


# ---------------------------------------------------------------------------
# Cross-process file lock (per session, plus migrate/GC coordination locks)
# ---------------------------------------------------------------------------


@contextmanager
def try_session_lock(
    lock_path: Path,
    timeout_seconds: float | None = None,
) -> Iterator[bool]:
    """Hold ``lock_path``'s exclusive byte-0 lock for the ``with`` body; yield
    whether it was acquired.

    The byte lock is :mod:`agent_runtime.file_locks`' (one owner of the
    platform split); this adds the bounded poll and the ``acquired: bool``
    contract the journal is written against — a chat turn never hangs on a stuck
    lock, it gets the typed ``SKIPPED_LOCK_TIMEOUT`` outcome. The handle opens
    ``r+b`` (created if absent) because the owner pads an empty file to one byte
    before locking it on Windows.
    """

    if timeout_seconds is None:
        timeout_seconds = _LOCK_TIMEOUT_SECONDS
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(str(lock_path), os.O_CREAT | os.O_RDWR), "r+b") as handle:
        acquired = False
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            try:
                try_lock_exclusive(handle)
                acquired = True
                break
            except (LockUnavailable, OSError):
                if time.monotonic() >= deadline:
                    break
                time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    unlock(handle)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Paths + per-file I/O
# ---------------------------------------------------------------------------


def _store_dir() -> Path:
    return paths.store_root() / _STORE_DIR_NAME


def _archive_dir() -> Path:
    return paths.store_root() / _ARCHIVE_DIR_NAME


def _legacy_store_path() -> Path:
    return paths.store_root() / _LEGACY_STORE_NAME


def _migrated_legacy_path() -> Path:
    return paths.store_root() / _LEGACY_MIGRATED_NAME


def _migrate_lock_path() -> Path:
    return paths.store_root() / _MIGRATE_LOCK_NAME


def _gc_lock_path() -> Path:
    return paths.store_root() / _GC_LOCK_NAME


def _session_filename_stem(session_key: str) -> str:
    """Deterministic, filesystem-safe, collision-free file stem for a session.

    A sanitized prefix keeps the file human-recognizable; a sha256 suffix over
    the exact (already length-bounded) session key guarantees two keys that
    sanitize to the same prefix still land in distinct files.
    """

    sanitized = "".join(
        ch if (ch.isalnum() or ch in "_.-") else "_" for ch in session_key
    ).strip("._-")[:_SESSION_KEY_PREFIX_MAX]
    digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:_SESSION_KEY_HASH_LEN]
    return f"{sanitized or 'session'}_{digest}"


def _session_file_path(session_key: str) -> Path:
    return _store_dir() / f"{_session_filename_stem(session_key)}{_SESSION_FILE_SUFFIX}"


def _session_lock_path(session_key: str) -> Path:
    return _store_dir() / f"{_session_filename_stem(session_key)}{_SESSION_LOCK_SUFFIX}"


def _lock_path_for_session_file(path: Path) -> Path:
    return path.with_name(path.name[: -len(_SESSION_FILE_SUFFIX)] + _SESSION_LOCK_SUFFIX)


def _iter_session_files() -> list[Path]:
    store_dir = _store_dir()
    try:
        return sorted(p for p in store_dir.glob(f"*{_SESSION_FILE_SUFFIX}") if p.is_file())
    except OSError:
        return []


def _read_session(session_key: str) -> dict[str, Any]:
    """Read one session's ``{client_message_id: record}`` map (migrate first)."""
    _migrate_legacy_if_present()
    return _read_session_map(_session_file_path(session_key))


def _read_session_map(path: Path) -> dict[str, Any]:
    """Pure single-file read — never triggers migration (used by GC/migration)."""
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_session_file(path: Path, session: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(session, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    # Lock-free journal readers can briefly hold the destination open on
    # Windows. Retry only the atomic rename; never truncate a committed journal
    # as a fallback, and preserve the original error on persistent denial.
    for attempt in range(5):
        try:
            tmp.replace(path)
            break
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 4:
                raise
            time.sleep(.02 * (attempt + 1))


def _session_file_recency(path: Path) -> tuple[str, float]:
    """Rank key for eviction (oldest first): newest ``updated_at`` in the file,
    falling back to the file mtime when the file carries no timestamps."""
    session = _read_session_map(path)
    recency = max(
        (
            str(record.get("updated_at") or "")
            for record in session.values()
            if isinstance(record, dict)
        ),
        default="",
    )
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (recency, mtime)


def _archive_session_file(path: Path) -> bool:
    """Move a session file under the archive dir (archive-never-delete).

    Returns True on success. A name collision (a session evicted, recreated,
    evicted again) is preserved with a nanosecond suffix rather than clobbered.
    A concurrent GC that already moved the file yields FileNotFoundError → False.
    """
    try:
        archive_dir = _archive_dir()
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / path.name
        if target.exists():
            target = archive_dir / f"{path.stem}.{time.time_ns()}{path.suffix}"
        os.replace(str(path), str(target))
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
