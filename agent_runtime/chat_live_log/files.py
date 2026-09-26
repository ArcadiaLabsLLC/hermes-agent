"""The mirror on disk and the process-wide state over it.

The captured root (+ its source, + the capture ladder) and the path it gives
each session; the claim + atomic publish and the bounded wait for someone
else's; append + rotate; the replay-dedupe index seeded from the file tail; the
failure tally. The three functions that ``global``-rebind a name live here WITH
the names — a ``global`` cannot rebind another module's variable.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from agent_runtime.paths import path_exists_safe, unlink_quietly

from agent_runtime.chat_live_log.lines import (
    _decode_lines,
    _encode,
    _normalized_role,
    _safe_session_token,
)

__layer__ = "stores"


logger = logging.getLogger(__name__)


#: Directory name under the resolved head home.
CHAT_LIVE_LOG_DIRNAME = "chat_live_logs"
_LOG_SUFFIX = ".jsonl"


#: Rotate at ~10MB into a single ``.1`` sibling.
LIVE_LOG_ROTATE_BYTES = 10 * 1024 * 1024


#: How much of an existing file the replay-dedupe index seeds from. Replays only
#: ever re-offer recent turns, so a bounded tail scan is enough and a 10MB file
#: never has to be read whole on a hot path.
_DEDUPE_TAIL_BYTES = 256 * 1024
#: Suffix of the claim/temp file a materialization publishes from.
_CLAIM_SUFFIX = ".materializing"
#: How long an appender waits for someone else's materialization to publish.
_CLAIM_WAIT_SECONDS = 1.0
#: A claim older than this belonged to a process that died mid-write.
_CLAIM_STALE_SECONDS = 120.0

_state_lock = threading.RLock()
_captured_root: Path | None = None
_captured_source: str | None = None
_seen_keys: dict[str, set[tuple[str, str]]] = {}
_seeded_sessions: set[str] = set()
_failures = 0
_failure_logged = False


# ── root capture ────────────────────────────────────────────────────────────


def capture_chat_live_log_root(*, session_db: Any = None, head_home: Any = None) -> Path | None:
    """Capture (once) the directory this process mirrors into.

    Safe to call repeatedly and from any lane; the first successful capture
    wins, except that a ``session_db``-derived root upgrades a scope-derived one
    (the database's own directory is the stronger answer). Never raises.
    """

    global _captured_root, _captured_source

    candidate: Path | None = None
    source = ""
    if head_home is not None:
        candidate = _coerce_dir(head_home)
        source = "explicit"
    if candidate is None and session_db is not None:
        candidate = _root_from_session_db(session_db)
        source = "session_db"
    if candidate is None:
        with _state_lock:
            if _captured_root is not None:
                return _captured_root
        candidate = _root_from_scope()
        source = "chat_session_scope"
    if candidate is None:
        return None

    with _state_lock:
        if _captured_root is None or (
            source in {"explicit", "session_db"} and _captured_source == "chat_session_scope"
        ):
            _captured_root = candidate / CHAT_LIVE_LOG_DIRNAME
            _captured_source = source
        return _captured_root


def chat_live_log_path(session_id: Any, *, session_db: Any = None) -> Path | None:
    """Where *session_id*'s mirror lives. Does not create anything."""

    token = _safe_session_token(session_id)
    if not token:
        return None
    root = capture_chat_live_log_root(session_db=session_db)
    if root is None:
        return None
    return root / f"{token}{_LOG_SUFFIX}"


def _with_claim(path: Path, work) -> Path | None:
    """Run *work* under an exclusive, cross-process claim on *path*.

    The claim file IS the temp file the work publishes from, so "a
    materialization is in flight" and "where the half-built content lives" are
    ONE fact rather than two that can disagree. ``O_EXCL`` is the cross-process
    gate; a claim older than :data:`_CLAIM_STALE_SECONDS` belonged to a process
    that died mid-write and is reclaimed rather than blocking this session's
    mirror forever.
    """

    claim = path.with_name(path.name + _CLAIM_SUFFIX)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _note_failure("mkdir", exc)
        return None
    handle: int | None = None
    for attempt in (0, 1):
        try:
            handle = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            # A live claim means somebody else is publishing: wait for it. A
            # STALE claim means its owner died mid-write — clear it and take
            # the work over, exactly once, so one crash cannot strand this
            # session's mirror permanently.
            if attempt == 0 and _claim_is_stale(claim):
                unlink_quietly(claim)
                continue
            return _wait_for_publication(path, claim)
        except OSError as exc:
            _note_failure("claim", exc)
            return None
    if handle is None:  # pragma: no cover - defensive
        return _wait_for_publication(path, claim)
    os.close(handle)
    try:
        return work(claim)
    finally:
        unlink_quietly(claim)


def _publish(path: Path, claim: Path, lines: list[dict[str, Any]]) -> Path | None:
    """Write *lines* to the claim file and atomically move it into position."""

    try:
        with open(claim, "w", encoding="utf-8", newline="\n") as handle:
            for payload in lines:
                handle.write(_encode(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, ValueError) as exc:
        _note_failure("materialize", exc)
        return None
    try:
        os.replace(claim, path)
    except OSError as exc:
        _note_failure("publish", exc)
        return None
    with _state_lock:
        # The file's identity changed underneath any cached dedupe index.
        _seeded_sessions.discard(path.stem)
        _seen_keys.pop(path.stem, None)
    return path


def _wait_for_publication(path: Path, claim: Path) -> Path | None:
    """Bounded wait for another process's materialization to land.

    An appender must not write into a file that is about to be replaced, and it
    must not give up so eagerly that a first-touch message is dropped. One
    second covers a hot-path create (which reads nothing); a long tool-lane
    materialization falls through and the caller simply skips this line —
    without marking it recorded, so the next attempt still writes it.
    """

    deadline = time.monotonic() + _CLAIM_WAIT_SECONDS
    while time.monotonic() < deadline:
        if path_exists_safe(path):
            return path
        if not path_exists_safe(claim):
            break
        time.sleep(0.02)
    return path if path_exists_safe(path) else None


def _backfill_pending(path: Path) -> bool:
    """Does this file's header still say history was never materialized?"""

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline()
    except OSError:
        return False
    try:
        row = json.loads(first)
    except ValueError:
        return False
    return bool(isinstance(row, dict) and row.get("backfill_pending"))


def reset_chat_live_log_state() -> None:
    """Drop the captured root and dedupe caches. TESTS ONLY."""

    global _captured_root, _captured_source, _failures, _failure_logged
    with _state_lock:
        _captured_root = None
        _captured_source = None
        _seen_keys.clear()
        _seeded_sessions.clear()
        _failures = 0
        _failure_logged = False


# ── internals ───────────────────────────────────────────────────────────────


def _root_from_session_db(session_db: Any) -> Path | None:
    raw = getattr(session_db, "db_path", None)
    if raw is None:
        return None
    try:
        parent = Path(str(raw)).expanduser().parent
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None
    return parent if str(parent) not in {"", "."} else None


def _root_from_scope() -> Path | None:
    try:
        from ..chat_session_scope import resolve_process_chat_scope

        # Process-wide log directory: no conversation is in hand here.
        return Path(resolve_process_chat_scope().head_home)
    except Exception:  # pragma: no cover - defensive
        return None


def _coerce_dir(value: Any) -> Path | None:
    try:
        candidate = Path(str(value)).expanduser()
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None
    return candidate if str(candidate) not in {"", "."} else None


def _claim_is_stale(claim: Path) -> bool:
    try:
        age = time.time() - claim.stat().st_mtime
    except OSError:
        return False
    return age > _CLAIM_STALE_SECONDS


def _append_line(path: Path, payload: dict[str, Any]) -> bool:
    try:
        blob = _encode(payload)
    except ValueError as exc:  # pragma: no cover - defensive
        _note_failure("encode", exc)
        return False
    try:
        _rotate_if_needed(path, len(blob.encode("utf-8")) + 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(blob + "\n")
        return True
    except OSError as exc:
        _note_failure("append", exc)
        return False


def _rotate_if_needed(path: Path, incoming_bytes: int) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size + incoming_bytes <= LIVE_LOG_ROTATE_BYTES:
        return
    try:
        os.replace(path, path.with_name(path.name + ".1"))
    except OSError as exc:  # pragma: no cover - defensive
        _note_failure("rotate", exc)


def _already_recorded(session_id: str, path: Path, key: tuple[str, str]) -> bool:
    with _state_lock:
        if session_id in _seeded_sessions:
            return key in _seen_keys.get(session_id, set())
    seen = _seed_from_tail(path)
    # A rotation moves recent turns into the ``.1`` sibling, leaving the live
    # file's tail empty; a fresh process would then happily re-append a resend
    # it had already recorded. Seed across the generation boundary.
    rotated = path.with_name(path.name + ".1")
    if path_exists_safe(rotated):
        seen |= _seed_from_tail(rotated)
    with _state_lock:
        _seen_keys.setdefault(session_id, set()).update(seen)
        _seeded_sessions.add(session_id)
        return key in _seen_keys[session_id]


def _mark_recorded(session_id: str, key: tuple[str, str]) -> None:
    with _state_lock:
        _seen_keys.setdefault(session_id, set()).add(key)
        _seeded_sessions.add(session_id)


def _seed_from_tail(path: Path) -> set[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > _DEDUPE_TAIL_BYTES:
                handle.seek(size - _DEDUPE_TAIL_BYTES)
                handle.readline()  # drop the partial line
            blob = handle.read()
    except OSError as exc:
        _note_failure("seed", exc)
        return seen
    for row in _decode_lines(blob):
        if row.get("kind") != "message":
            continue
        client = str(row.get("client_message_id") or "")
        if client:
            seen.add((_normalized_role(row.get("role")), client))
    return seen


def _note_failure(step: str, exc: Exception | None = None) -> bool:
    """Count a mirror failure; log the FIRST one only.

    Silence would make a broken mirror indistinguishable from an idle one; a log
    line per failed append would flood a chat turn's log. One line plus a
    running count is the honest middle.
    """

    global _failures, _failure_logged
    with _state_lock:
        _failures += 1
        should_log = not _failure_logged
        _failure_logged = True
    if should_log:
        logger.warning(
            "chat live-log mirror write failed (%s): %s — the transcript itself is "
            "unaffected; the mirror is a regenerable artifact",
            step,
            exc,
        )
    return False
