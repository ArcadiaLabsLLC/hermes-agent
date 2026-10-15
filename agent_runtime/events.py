from __future__ import annotations

import bisect
import itertools
import json
import logging
import os
import re
import threading
from collections import Counter
from collections.abc import Collection, Iterator
from datetime import datetime
from typing import Any

from . import event_rotation, paths
from .decision_contract_registry import allowed_event_types, validate_event_payload
from .errors import EventPayloadTooLarge
from .locks import events_lock
from .models import EVENT_PAYLOAD_LIMIT_BYTES, Event, payload_bytes
from .serde import from_jsonable, to_jsonable

__layer__ = "stores"

# Match compact-JSON top-level id tokens while still treating the parsed event
# as authoritative. Payload copies may add candidates, but never false results.
_INDEXED_EVENT_ID_TOKEN_RE = re.compile(
    r'"(?:task_id|session_id)":(?:(?:"(?:\\.|[^"\\])*")|null)'
)

# Env override for the rotation cap (operator/test knob). When unset the
# config-derived cap is used, memoized per store root so the hot append path
# does not re-parse config on every event.
_ROTATION_CAP_ENV = "HERMES_EVENT_LOG_ROTATION_CAP_BYTES"
_ROTATION_CAP_CACHE: dict[str, int] = {}

# The one process-wide event view per store (keyed by the oldest slice's path).
# Sealed slices are immutable; the live slice only grows, so a view whose slice
# list and sealed stats still match reads just the bytes appended since its last
# refresh and indexes only those lines. The view's lists only ever grow in place:
# each CachedEventLog pins a line COUNT when it materializes, so a reader never
# sees lines appended after it started (a point-in-time view without a copy).
# A new slice, a moved sealed stat, or a live slice that shrank (or was rewritten
# at the same size) rebuilds the view whole, into fresh lists.
_EVENT_VIEWS: dict[str, "_EventView"] = {}
_EVENT_VIEW_CACHE_LOCK = threading.Lock()
_EVENT_VIEW_CACHE_MAX = 8


def _event_view_cache_clear() -> None:
    """Test hook — drop every process-wide event view."""

    with _EVENT_VIEW_CACHE_LOCK:
        _EVENT_VIEWS.clear()


def _rotation_cap_bytes() -> int:
    """Resolve the live-slice rotation cap. Env override wins; else the
    ``event_log.rotation_cap_bytes`` config value (default 16 MiB), memoized per
    store root. ``0`` disables rotation."""

    env = os.environ.get(_ROTATION_CAP_ENV)
    if env:
        try:
            value = int(env)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    try:
        root = str(paths.store_root())
    except Exception:
        return event_rotation.DEFAULT_ROTATION_CAP_BYTES
    cached = _ROTATION_CAP_CACHE.get(root)
    if cached is not None:
        return cached
    cap = event_rotation.DEFAULT_ROTATION_CAP_BYTES
    try:
        from .config import load_root_runtime_config

        raw = getattr(getattr(load_root_runtime_config(), "event_log", None), "rotation_cap_bytes", None)
        if raw is not None:
            cap = max(0, int(raw))
    except Exception:
        cap = event_rotation.DEFAULT_ROTATION_CAP_BYTES
    _ROTATION_CAP_CACHE[root] = cap
    return cap

ALLOWED_EVENT_TYPES = allowed_event_types()

# Every row here must also be in ``ALLOWED_EVENT_TYPES`` — a summary rule for a
# de-registered type describes a shape ``EventLog.append`` refuses, so it can
# only ever be exercised by a test minting an event no reader will ever see.
# S21 dropped ``delivery.intent``, ``patch.proposed``, ``role_session.closed``,
# and ``run.approval_required`` for exactly that reason (S15 de-registered all
# four), together with their branches in ``operator_event_summary``.
# S25 dropped ``run.opened`` under the same rule once its contract went (its
# writer ``RunStore.open_run`` went at S17). Historical rows are unaffected —
# ``append`` type-checks on WRITE only, so the 1,882 ``run.opened`` rows in the
# live log still read back — and none of them lose a rendered summary in
# practice: ``operator_event_summary``'s only read-side consumer is
# ``snapshot._event_display_projection``, which is reached solely from three
# task-scoped projections that have had ZERO callers since the ``Task`` record
# went at S8. ``repo_bundle.delivered`` went in the same pass and for the same
# rule, one commit behind its emitter: S24 deleted
# ``RepoBundleStore.mark_delivered``, the only writer that ever produced it,
# while every other ``repo_bundle.*`` type still rode a live
# ``RepoBundleStore.update``.
#
# S52 (2026-08-01) finished that lane: the whole ``RepoBundleStore`` WRITE side
# was deleted for want of a production caller, so ``repo_bundle.updated`` and
# ``repo_bundle.assigned`` -- the last two ``repo_bundle.*`` types in this
# frozenset -- were de-registered with it and removed from here. The S21/S25
# invariant is why this edit is not optional: this frozenset may not name a
# de-registered type, and ``operator_event_summary`` early-returns ``None``
# outside it, so their shared formatter arm became unreachable the moment the
# registration went and was removed in the same commit.
OPERATOR_SUMMARY_EVENT_TYPES = frozenset(
    {
        "run.closed",
        "run.progress",
        "run.tool.started",
        "run.tool.finished",
    }
)


def _strict_event_contracts() -> bool:
    """Contract validation posture (Stage 12 D): strict in tests/CI via
    HERMES_EVENT_CONTRACT_STRICT, observe-and-warn live — a validation bug
    must never take down the runtime, but CI must not let a violation land."""

    return str(os.environ.get("HERMES_EVENT_CONTRACT_STRICT", "")).strip().lower() in {"1", "true", "yes", "on"}


# Observe-mode dedupe: warn once per (type, missing-fields) shape per process.
# High-frequency emitters (run.heartbeat every few seconds) must not turn a
# contract drift into log spam; one line per shape is enough to find the bug.
_WARNED_CONTRACT_SHAPES: set[tuple[str, tuple[str, ...]]] = set()


class EventLog:
    def append(self, evt: Event) -> None:
        if evt.type not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"unknown event type: {evt.type}")
        missing = validate_event_payload(evt.type, evt.payload)
        if missing:
            message = f"event {evt.type} payload missing contract summary fields: {missing}"
            if _strict_event_contracts():
                raise ValueError(message)
            shape = (evt.type, missing)
            if shape not in _WARNED_CONTRACT_SHAPES:
                _WARNED_CONTRACT_SHAPES.add(shape)
                logging.getLogger(__name__).warning(message)
        evt = event_with_operator_summary(evt)
        size = payload_bytes(evt.payload)
        if size > EVENT_PAYLOAD_LIMIT_BYTES:
            raise EventPayloadTooLarge(
                f"event payload is {size} bytes; limit is {EVENT_PAYLOAD_LIMIT_BYTES}"
            )
        line = json.dumps(to_jsonable(evt), ensure_ascii=False, separators=(",", ":"))
        with events_lock():
            # Rotate-before-write (under the lock): if the current live slice has
            # reached the cap, seal it and open a fresh one, THEN write this line
            # into the fresh slice — the live slice is never left empty after a
            # completed append (keeps tail(1)/watermark honest). Windows-safe:
            # rotation only creates a new file + rewrites the manifest, so a
            # concurrent reader holding the sealed file open is never disturbed.
            path = event_rotation.prepare_live_for_append(_rotation_cap_bytes())
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()

    def tail(self, n: int) -> list[Event]:
        if n <= 0:
            return []
        selected: list[str] = []
        for sl in event_rotation.reversed_slices():
            if not sl.path.exists():
                continue
            for line in _reversed_slice_lines(sl.path):
                if not line.strip():
                    continue
                selected.append(line)
                if len(selected) >= n:
                    return [from_jsonable(Event, json.loads(row)) for row in reversed(selected)]
        return [from_jsonable(Event, json.loads(row)) for row in reversed(selected)]

    def iter_from_offset(self, offset: int) -> Iterator[tuple[int, Event]]:
        # Logical-offset tailing across slices: resolve which slice(s) a logical
        # offset lives in and seek there, yielding logical offsets throughout so
        # every reader/watermark resolves unchanged across a rotation boundary.
        start = max(0, int(offset or 0))
        for slice_path, slice_start, seek_within in event_rotation.offset_reads(start):
            if not slice_path.exists():
                continue
            with open(slice_path, "rb") as handle:
                handle.seek(seek_within)
                for raw in handle:
                    if not raw.strip():
                        continue
                    logical_offset = slice_start + handle.tell()
                    yield logical_offset, from_jsonable(Event, json.loads(raw.decode("utf-8")))

    def _for_matching(
        self,
        token: str,
        match,
        *,
        limit: int,
        since: datetime | None,
        types: Collection[str] | None,
    ) -> list[Event]:
        """Newest-first reverse scan across slices (newest slice first), stopping
        once ``limit`` matches are collected, returned oldest-first. Each slice is
        read from its end in chunks (``_reversed_slice_lines``), so a scan whose
        ``limit`` is met in the tail never reads the rest of an 11–81 MB slice;
        ``limit <= 0`` still walks every line of every slice."""

        type_tokens = _type_json_tokens(types)
        selected: list[Event] = []
        for sl in event_rotation.reversed_slices():
            if not sl.path.exists():
                continue
            for line in _reversed_slice_lines(sl.path):
                if token not in line:
                    continue
                if type_tokens is not None and not any(t in line for t in type_tokens):
                    continue
                evt = from_jsonable(Event, json.loads(line))
                if not match(evt):
                    continue
                if types is not None and evt.type not in types:
                    continue
                if since is not None and evt.ts < since:
                    continue
                selected.append(evt)
                if limit > 0 and len(selected) >= limit:
                    return list(reversed(selected))
        return list(reversed(selected))

    def for_task(
        self,
        task_id: str,
        *,
        limit: int = 50,
        since: datetime | None = None,
        types: Collection[str] | None = None,
    ) -> list[Event]:
        """Return the newest events for ``task_id``, oldest-first.

        When ``types`` is given, ``limit`` counts only events whose ``type`` is in
        that set — a busy task whose recent tail is flooded with non-matching rows
        (e.g. an incident loop) can no longer starve the window before the type
        filter runs. The type-token substring pre-filter keeps the reverse scan
        cheap even against such floods.
        """

        return self._for_matching(
            _task_id_json_token(task_id),
            lambda evt: evt.task_id == task_id,
            limit=limit,
            since=since,
            types=types,
        )

    def for_session(
        self,
        session_id: str,
        *,
        limit: int = 50,
        since: datetime | None = None,
        types: Collection[str] | None = None,
    ) -> list[Event]:
        """Return events bound to a conversational chat ``session_id``.

        Mirrors :meth:`for_task` but matches on the event ``session_id`` lineage
        instead of ``task_id``. Used by the snapshot trace projection to surface
        tool/progress events recorded during a (non-task) persona chat turn. The
        substring pre-filter keeps the reverse scan cheap; task-run events carry
        ``"session_id":null`` and are skipped by both the token and the
        post-decode equality check. ``types`` behaves as in :meth:`for_task`.
        """

        return self._for_matching(
            _session_id_json_token(session_id),
            lambda evt: evt.session_id == session_id,
            limit=limit,
            since=since,
            types=types,
        )

# S54 removed ``archive_task_events`` and ``compact_archived_task_events``.
# Both were task-scoped event archivers whose last caller went with the ``Task``
# record at S8; the only references left were their own tests.

def event_log_health() -> dict[str, Any]:
    path = paths.events_path()
    rotation = event_rotation.rotation_health()
    # Whole-log totals span all slices; ``exists`` stays keyed on the canonical
    # base file for backward compatibility (it remains present as the sealed
    # base-0 slice after rotation).
    size_bytes = rotation["total_bytes"]
    line_count = rotation["total_lines"]
    exists = path.exists() or size_bytes > 0
    archive = _archived_event_slices()
    return {
        "exists": exists,
        "size_bytes": size_bytes,
        "line_count": line_count,
        "archived_event_slices": len(archive["slices"]),
        "archived_event_rows": archive["row_count"],
        "index_health": "ok" if exists or archive["row_count"] == 0 else "archive_only",
        # Rotation accounting (C6a): the live slice is bounded; sealed rotation
        # slices are archive-never-delete and offset-load-bearing.
        "rotated_slice_count": rotation["rotated_slice_count"],
        "live_slice_file": rotation["live_slice_file"],
        "live_slice_bytes": rotation["live_slice_bytes"],
        "live_slice_lines": rotation["live_slice_lines"],
        "log_end_offset": rotation["log_end_offset"],
    }


class CachedEventLog(EventLog):
    """Build-scoped EventLog that reads the event log ONCE and serves every read
    from the cached raw lines.

    A single snapshot build calls ``for_task`` / ``for_session`` / ``tail`` dozens
    of times; the base ``EventLog`` re-reads + re-splits the entire log on each
    call (the dominant repeated cost). This caches the split lines once and keeps
    the base's *selective* parse (substring pre-filter → ``json.loads`` only on
    matching lines), so it dedupes the file I/O without paying to parse every
    event. It is a point-in-time view: each builder gets its own object pinned to
    a line count of the one process-wide view per store (``_EVENT_VIEWS``). Appends
    made elsewhere during a build are intentionally not reflected; the next
    builder observes the live slice's new size and the view reads ONLY the
    appended bytes (whole lines; a torn final line waits for the next refresh)
    and indexes only those lines. A rotation, a moved sealed stat or a live slice
    that shrank rebuilds the view whole.

    Rotation (C6a): the cache concatenates every slice oldest-first (rotated
    archive slices + live). Slices are contiguous in logical-offset space and the
    first slice starts at logical 0, so the flat concatenation's cumulative byte
    position IS the logical offset — ``iter_from_offset`` keeps resolving watermark
    cursors unchanged. Pristine (single live slice) reads only ``events.jsonl``.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lines: list[str] | None = None
        self._positions_by_id_token: dict[str, list[int]] | None = None
        self._line_count = 0

    def _cached_lines(self) -> list[str]:
        """Pin this reader's point-in-time view of the process-wide event view.

        Returns the view's shared, append-only line list; only its first
        ``self._line_count`` lines belong to this reader — every read below
        bounds itself by that count, never by ``len()``.
        """

        if self._lines is None:
            self._lines, self._positions_by_id_token, self._line_count = _acquire_event_view()
        return self._lines

    def _scan(
        self,
        token: str,
        match,
        *,
        limit: int,
        since: datetime | None,
        types: Collection[str] | None = None,
    ) -> list[Event]:
        type_tokens = _type_json_tokens(types)
        selected: list[Event] = []
        lines = self._cached_lines()
        positions = (self._positions_by_id_token or {}).get(token, ())
        # Positions ascend; the ones at or past this reader's count were indexed
        # by a later refresh and are not part of this point-in-time view.
        for at in range(bisect.bisect_left(positions, self._line_count) - 1, -1, -1):
            line = lines[positions[at]]
            if token not in line:
                continue
            if type_tokens is not None and not any(type_token in line for type_token in type_tokens):
                continue
            evt = from_jsonable(Event, json.loads(line))
            if not match(evt):
                continue
            if types is not None and evt.type not in types:
                continue
            if since is not None and evt.ts < since:
                continue
            selected.append(evt)
            if limit > 0 and len(selected) >= limit:
                break
        return list(reversed(selected))

    def for_task(
        self,
        task_id: str,
        *,
        limit: int = 50,
        since: datetime | None = None,
        types: Collection[str] | None = None,
    ) -> list[Event]:
        return self._scan(
            _task_id_json_token(task_id),
            lambda evt: evt.task_id == task_id,
            limit=limit,
            since=since,
            types=types,
        )

    def for_session(
        self,
        session_id: str,
        *,
        limit: int = 50,
        since: datetime | None = None,
        types: Collection[str] | None = None,
    ) -> list[Event]:
        return self._scan(
            _session_id_json_token(session_id),
            lambda evt: evt.session_id == session_id,
            limit=limit,
            since=since,
            types=types,
        )

    def tail(self, n: int) -> list[Event]:
        if n <= 0:
            return []
        lines = self._cached_lines()
        count = self._line_count
        return [from_jsonable(Event, json.loads(line)) for line in lines[max(0, count - n):count] if line.strip()]

    def iter_from_offset(self, offset: int) -> Iterator[tuple[int, Event]]:
        # Whole-view semantics kept: the logical offset is the cumulative byte
        # position of the flat concatenation, so this walks from the first line.
        current = 0
        start = max(0, int(offset or 0))
        lines = self._cached_lines()
        for line in itertools.islice(lines, self._line_count):
            raw = (line + "\n").encode("utf-8")
            current += len(raw)
            if current <= start or not line.strip():
                continue
            yield current, from_jsonable(Event, json.loads(line))


class _EventView:
    """One store's event log as split lines plus an id-token index of positions.

    ``consumed`` is the live slice's byte count already split into ``lines`` —
    always just past a ``\\n``, so a torn final line is left for the next refresh.
    """

    __slots__ = ("sources", "sealed_stamps", "live_stamp", "consumed", "lines", "positions")

    def __init__(self, sources, sealed_stamps, live_stamp, consumed, lines, positions) -> None:
        self.sources: tuple[str, ...] = sources
        self.sealed_stamps: tuple[tuple[int, int, int], ...] = sealed_stamps
        self.live_stamp: tuple[int, int, int] = live_stamp
        self.consumed: int = consumed
        self.lines: list[str] = lines
        self.positions: dict[str, list[int]] = positions


def _slice_stamp(path) -> tuple[int, int, int]:
    """``(inode, mtime_ns, size)``: a slice replaced by a new file is a new slice."""

    try:
        stat = path.stat()
    except OSError:
        return (-1, -1, -1)
    return (stat.st_ino, stat.st_mtime_ns, stat.st_size)


def _read_live_from(path, start: int) -> bytes:
    """The live slice's bytes from ``start`` to its end — the one live-slice read."""

    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            return handle.read()
    except FileNotFoundError:
        return b""


def _whole_lines(data: bytes) -> tuple[list[str], int]:
    """Split ``data`` up to its last ``\\n``; return the lines and the bytes used."""

    used = data.rfind(b"\n") + 1
    return data[:used].decode("utf-8").splitlines(), used


def _index_lines(lines: list[str], positions: dict[str, list[int]], start: int) -> None:
    for at in range(start, len(lines)):
        # One position per token bucket regardless of how many times the token
        # appears in the line — a payload echoing its own id must not double the
        # event. Two DIFFERENT tokens on one line still index it once each.
        for token in {match.group(0) for match in _INDEXED_EVENT_ID_TOKEN_RE.finditer(lines[at])}:
            positions.setdefault(token, []).append(at)


def _build_event_view(sources, sealed, sealed_stamps, live, live_stamp) -> _EventView:
    lines: list[str] = []
    for source in sealed:
        if source.exists():
            lines.extend(source.read_text(encoding="utf-8").splitlines())
    appended, consumed = _whole_lines(_read_live_from(live, 0))
    lines.extend(appended)
    positions: dict[str, list[int]] = {}
    _index_lines(lines, positions, 0)
    return _EventView(sources, sealed_stamps, live_stamp, consumed, lines, positions)


def _append_to_event_view(view: _EventView, sources, sealed_stamps, live, live_stamp) -> bool:
    """Bring ``view`` up to date in place by reading only the live slice's
    appended bytes. False when it cannot: the slice list or a sealed stat moved
    (a rotation, an edit), or the live slice shrank, was replaced, or was
    rewritten."""

    if view.sources != sources or view.sealed_stamps != sealed_stamps:
        return False
    if live_stamp == view.live_stamp:
        return True
    inode, _mtime, size = live_stamp
    if inode != view.live_stamp[0] or size < view.consumed or size <= view.live_stamp[2]:
        return False
    # Re-read the byte before ``consumed``: it must still be the ``\n`` the last
    # refresh stopped after, or the consumed prefix was rewritten.
    start = view.consumed - 1 if view.consumed else 0
    data = _read_live_from(live, start)
    if view.consumed:
        if data[:1] != b"\n":
            return False
        data = data[1:]
    appended, used = _whole_lines(data)
    first_new = len(view.lines)
    view.lines.extend(appended)
    _index_lines(view.lines, view.positions, first_new)
    view.consumed += used
    view.live_stamp = live_stamp
    return True


def _acquire_event_view() -> tuple[list[str], dict[str, list[int]], int]:
    """The current view's lines, index and line count, refreshed under the lock."""

    slice_paths = list(event_rotation.ordered_line_sources())
    *sealed, live = slice_paths
    sources = tuple(str(path) for path in slice_paths)
    sealed_stamps = tuple(_slice_stamp(path) for path in sealed)
    live_stamp = _slice_stamp(live)
    with _EVENT_VIEW_CACHE_LOCK:
        view = _EVENT_VIEWS.get(sources[0])
        if view is None or not _append_to_event_view(view, sources, sealed_stamps, live, live_stamp):
            view = _build_event_view(sources, sealed, sealed_stamps, live, live_stamp)
            if sources[0] not in _EVENT_VIEWS and len(_EVENT_VIEWS) >= _EVENT_VIEW_CACHE_MAX:
                _EVENT_VIEWS.clear()
            _EVENT_VIEWS[sources[0]] = view
        return view.lines, view.positions, len(view.lines)


_REVERSE_READ_CHUNK_BYTES = 1 << 20


def _reversed_slice_lines(path) -> Iterator[str]:
    r"""Yield ``path``'s lines newest-first, reading the file from its end.

    The same lines, in the same order, as
    ``reversed(path.read_text(encoding="utf-8").splitlines())`` — including an
    unterminated (torn) final line on a live slice and ``splitlines``' extra
    breaks (``\r``, U+2028, U+0085 …) — without reading or decoding the bytes
    before the point where the caller stops. The size is taken once at open: an
    append racing the scan is not seen, as a finished ``read_text`` would not
    have seen it. Each chunk is cut after its first ``\n`` so only whole lines
    are decoded; the head carries into the next (earlier) chunk. ``\n`` never
    occurs inside a UTF-8 multi-byte sequence, and every block but the file's
    last ends in ``\n``, so ``splitlines`` of the blocks concatenates to
    ``splitlines`` of the file. One divergence: undecodable bytes raise only if
    the scan reaches them, not because they exist anywhere in the slice.
    """

    chunk_bytes = max(1, int(_REVERSE_READ_CHUNK_BYTES))
    with open(path, "rb") as handle:
        pos = handle.seek(0, os.SEEK_END)
        carry = b""
        while pos > 0:
            step = min(chunk_bytes, pos)
            pos -= step
            handle.seek(pos)
            block = handle.read(step) + carry
            if pos > 0:
                cut = block.find(b"\n")
                if cut < 0:
                    carry = block
                    continue
                carry, block = block[: cut + 1], block[cut + 1 :]
            else:
                carry = b""
            yield from reversed(block.decode("utf-8").splitlines())


def _task_id_json_token(task_id: str) -> str:
    encoded = json.dumps(str(task_id), ensure_ascii=False, separators=(",", ":"))
    return f'"task_id":{encoded}'


def _session_id_json_token(session_id: str) -> str:
    encoded = json.dumps(str(session_id), ensure_ascii=False, separators=(",", ":"))
    return f'"session_id":{encoded}'


def _type_json_tokens(types: Collection[str] | None) -> tuple[str, ...] | None:
    """Literal ``"type":"…"`` substrings for the compact-JSON line pre-filter.

    Safe because :meth:`EventLog.append` writes every line with
    ``separators=(",", ":")`` — the token form is stable. ``None`` disables the
    pre-filter (untyped scan).
    """

    if types is None:
        return None
    return tuple(
        f'"type":{json.dumps(str(event_type), ensure_ascii=False, separators=(",", ":"))}'
        for event_type in sorted(types)
    )


# S54 also took ``_safe_event_task_filename`` and ``_line_is_compacted_event``
# with the two archivers above -- each was reachable only from them. A private
# helper outliving its only caller is the residue S25 named when it retired
# ``_safe_int`` with the formatter arm that used it.

def _archived_event_slices() -> dict[str, Any]:
    archive_root = paths.deleted_archive_dir()
    line_counts: Counter[str] = Counter()
    task_ids: set[str] = set()
    slices: list[dict[str, Any]] = []
    row_count = 0
    if not archive_root.exists():
        return {"line_counts": line_counts, "task_ids": task_ids, "slices": slices, "row_count": row_count}
    for manifest_path in sorted(archive_root.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        batch_dir = manifest_path.parent
        for item in manifest.get("archived_tasks") or []:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("task_id") or "").strip()
            event_rel = str(item.get("events_path") or "").strip()
            if not task_id or not event_rel:
                continue
            event_path = batch_dir / event_rel
            if not event_path.exists():
                continue
            task_ids.add(task_id)
            count = 0
            with open(event_path, encoding="utf-8") as handle:
                for line in handle:
                    normalized = line if line.endswith("\n") else f"{line}\n"
                    if normalized.strip():
                        line_counts[normalized] += 1
                        count += 1
            row_count += count
            slices.append(
                {
                    "archive_batch": batch_dir.name,
                    "task_id": task_id,
                    "events_path": event_rel,
                    "event_count": count,
                }
            )
    return {"line_counts": line_counts, "task_ids": task_ids, "slices": slices, "row_count": row_count}


def event_with_operator_summary(evt: Event) -> Event:
    """Ensure operator-visible events always carry a redaction-safe summary."""

    payload = evt.payload if isinstance(evt.payload, dict) else {}
    summary = operator_event_summary(evt)
    changed = payload is not evt.payload
    if evt.type == "run.progress" and not _safe_text(payload.get("event_id")):
        event_id = _progress_event_id(evt, payload)
        if event_id:
            payload = dict(payload)
            payload["event_id"] = event_id
            changed = True
    if summary and _safe_text(payload.get("summary")) != summary:
        payload = dict(payload)
        payload["summary"] = summary
        changed = True
    if not changed:
        return evt
    return Event(
        ts=evt.ts,
        type=evt.type,
        task_id=evt.task_id,
        run_id=evt.run_id,
        persona_id=evt.persona_id,
        payload=payload,
        session_id=evt.session_id,
        turn_id=evt.turn_id,
    )


def operator_event_summary(evt: Event) -> str | None:
    if evt.type not in OPERATOR_SUMMARY_EVENT_TYPES:
        return None
    payload = evt.payload if isinstance(evt.payload, dict) else {}
    existing = _safe_text(payload.get("summary"))
    if existing:
        return existing
    event_type = evt.type
    if event_type == "run.closed":
        actor = _label(evt.persona_id, "agent")
        state = _safe_text(payload.get("state")) or "closed"
        decision = _safe_text(payload.get("decision_type"))
        return f"Closed {actor} run as {state}" + (f" after {decision}." if decision else ".")
    # S52 removed the shared ``repo_bundle.assigned`` / ``repo_bundle.updated``
    # arm that stood here. Both types left OPERATOR_SUMMARY_EVENT_TYPES with the
    # RepoBundleStore write lane, and this function early-returns None above for
    # anything outside that frozenset, so the arm was unreachable the moment the
    # registration went -- the same S25 rule that retired the ``delivered`` arm
    # and its ``_safe_int`` helper.
    if event_type == "run.progress":
        parts = [
            _safe_text(payload.get("phase")),
            _safe_text(payload.get("step")),
            _safe_text(payload.get("status")),
        ]
        text = " ".join(part for part in parts if part)
        return f"Progress: {text}." if text else "Run progress update."
    if event_type.startswith("run.tool."):
        tool = _safe_text(payload.get("tool_name")) or _safe_text(payload.get("tool")) or "tool"
        status = _safe_text(payload.get("status")) or ("started" if event_type.endswith(".started") else "finished")
        return f"{tool} {status}."
    return event_type.replace(".", " ").title() + "."


def event_summary_missing(evt: Event) -> bool:
    if evt.type not in OPERATOR_SUMMARY_EVENT_TYPES:
        return False
    payload = evt.payload if isinstance(evt.payload, dict) else {}
    return not bool(_safe_text(payload.get("summary")))


def _progress_event_id(evt: Event, payload: dict) -> str | None:
    run_id = _safe_token(evt.run_id) or _safe_token(payload.get("run_id"))
    if not run_id:
        return None
    phase = _safe_token(payload.get("phase"))
    if not phase:
        return None
    step = _safe_token(payload.get("step")) or "update"
    command_index = _safe_token(payload.get("command_index"))
    timing_key = _safe_token(payload.get("timing_key"))
    proof_id = _safe_token(payload.get("proof_id"))
    parts = ["progress", run_id, phase, step]
    for value in (command_index, timing_key, proof_id):
        if value:
            parts.append(value)
    return ":".join(parts)


def _safe_text(value, *, limit: int = 240) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    if not text or _looks_sensitive_or_pathish(text):
        return None
    return f"{text[: limit - 3]}..." if len(text) > limit else text


def _label(value, fallback: str) -> str:
    return (_safe_text(value, limit=80) or fallback).replace("_", " ")


def _safe_token(value) -> str | None:
    text = str(value or "").strip()
    if not text or _looks_sensitive_or_pathish(text):
        return None
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "_", text)[:120].strip("_")
    return safe or None


def _looks_sensitive_or_pathish(value: str) -> bool:
    lowered = value.lower()
    sensitive_markers = (
        "secret",
        "token",
        "password",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "cookie",
        "private_key",
        "sk-",
        "passwd",
    )
    if any(marker in lowered for marker in sensitive_markers):
        return True
    if ":/" in value or "\\" in value or value.startswith(("/", "~")):
        return True
    if re.search(r"(^|\s)([A-Za-z]:)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        return True
    return bool(re.search(r"(^|\s)[A-Za-z0-9_.-]+\.(dart|py|js|ts|json|yaml|yml|md|txt)/", value, re.IGNORECASE))
