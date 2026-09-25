"""The on-disk generation layout: the cache directory, the pointer, live
generation resolution, and the core / sidecar / entries paths.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from agent_runtime.core_cache.vocabulary import (
    CORE_CACHE_DIRNAME,
    CORE_FILENAME,
    ENTRIES_FILENAME,
    POINTER_FILENAME,
    SIDECAR_FILENAME,
    _GENERATION_PREFIX,
    _NO_GENERATION_DIRNAME,
)

__layer__ = "stores"

__all__ = [
    "_cache_dir",
    "_core_digest",
    "_is_generation_name",
    "_live_generation_dir",
    "_live_generation_name",
    "_new_generation_name",
    "core_path",
    "entries_path",
    "pointer_path",
    "sidecar_path",
]


def _cache_dir() -> Path:
    from .. import paths as _paths

    return _paths.store_root() / CORE_CACHE_DIRNAME


def pointer_path() -> Path:
    """The file whose replacement IS the write-back (MCF-21)."""

    return _cache_dir() / POINTER_FILENAME


def _is_generation_name(name: Any) -> bool:
    """Whether ``name`` is a generation directory this module could have minted.

    CONTAINMENT, not tidiness. The name comes off disk, out of a file any process
    on the machine can write, and it is about to be joined onto
    :func:`_cache_dir`. ``..`` or a separator would resolve the "live trio"
    anywhere on the filesystem, and the judgement downstream would then be asked
    to bless bytes this module never wrote. The charset admits exactly what
    :func:`_new_generation_name` mints and nothing else — no dots, no separators,
    no drive letters — so escaping is unrepresentable rather than filtered.
    """

    if not isinstance(name, str) or not name.startswith(_GENERATION_PREFIX):
        return False
    body = name[len(_GENERATION_PREFIX) :]
    return bool(body) and all(char in "0123456789abcdef-" for char in body)


def _new_generation_name() -> str:
    """A generation name no other write-back can collide with.

    The timestamp is for the OPERATOR — a directory listing of the cache sorts
    into the order the write-backs happened, which is what makes a stranded
    staging directory legible. It is NOT how the live generation is chosen: the
    pointer is the only authority, and a reader that preferred the newest name or
    mtime would resurrect a generation whose publish never completed. The random
    tail is what makes the name unique across two processes writing back inside
    the same nanosecond.
    """

    return f"{_GENERATION_PREFIX}{time.time_ns():x}-{uuid.uuid4().hex[:8]}"


def _live_generation_dir() -> Path:
    """The directory holding the trio the pointer names.

    =========================================================================
    WHY A POINTER AND NOT A DIRECTORY SWAP
    =========================================================================

    MC-3 recorded the target shape as "write ``serve_read_model.next/``,
    ``os.replace`` the directory". That is not implementable, and the reason is a
    platform fact rather than a preference: ``os.replace`` cannot replace a
    NON-EMPTY directory anywhere (POSIX ``rename`` answers ``ENOTEMPTY``), and on
    Windows — the primary platform — it cannot replace a directory AT ALL, empty
    or not (measured 2026-08-18: ``PermissionError`` / ``WinError 5`` for both).
    A directory can only be renamed onto a name that does not exist.

    The shape that follows from that is rename-away-then-rename-in, and it is
    REFUSED: between the two renames there is no live generation at all, so a
    concurrent consult is served ``absent`` — a window strictly worse than the
    torn trio the swap exists to retire.

    So the atomicity rides ONE small file instead. The complete trio is written
    into a fresh generation directory that nothing points at, and the write-back
    lands when — and only when — the pointer naming it is replaced through
    :func:`utils.atomic_json_write`, the same single atomic-write authority the
    rest of this module already uses. A crash before that leaves a directory the
    pointer never named, which serves nobody and is reaped by the next successful
    write-back.

    =========================================================================
    A POINTERLESS STORE DEMOTES — IT DOES NOT ADOPT THE FLAT TRIO
    =========================================================================

    Every store that held a cache before MCF-21 has ``core.json`` /
    ``sidecar.json`` / ``entries.json`` sitting flat in :func:`_cache_dir`, and
    adopting them as generation zero was the alternative on offer. It is refused,
    and NOT because the judgement could not vet them — it could; the full
    conjunction in :func:`_judge_persisted_pair` is exactly what a torn legacy
    trio fails. It is refused because keeping a second resolution alive forever
    means a pointer that is ever LOST — deleted, truncated, unparseable — silently
    falls back to whatever flat trio is on disk. That path can serve an arbitrarily
    old core as authoritative, which is the missed-input direction this module
    calls its worst failure, reached through the one code path nobody exercises.

    The cost of refusing is exactly one demote, on the first boot after this
    lands, on each store. A cache's cold start is its designed-for state.
    """

    name = _live_generation_name()
    return _cache_dir() / (name if name is not None else _NO_GENERATION_DIRNAME)


def _live_generation_name() -> str | None:
    """What the pointer says, or ``None`` when nothing usable does.

    Never raises, and every unusable shape answers the SAME way — no pointer, an
    unreadable one, a non-object, a missing field, a name that is not one this
    module mints. They are one fact ("no generation is published") and giving
    them one answer is what keeps the caller from growing a second judgement.
    """

    try:
        payload = json.loads(pointer_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("generation")
    return name if _is_generation_name(name) else None


def core_path() -> Path:
    return _live_generation_dir() / CORE_FILENAME


def sidecar_path() -> Path:
    return _live_generation_dir() / SIDECAR_FILENAME


def entries_path() -> Path:
    """The stat set behind the sidecar's digest, so a miss can name a path.

    **The binding rule, RE-AIMED by MCF-21.** The payload is
    ``{"fingerprint": <digest>, "entries": [[path, mtime_ns, size], …]}`` and a
    reader compares ``entries.fingerprint`` against the sidecar's, refusing
    ``diff_reason=entries_unbound`` when they differ.

    The reason it was written is GONE, and saying so is the point. It used to
    guard POSITIONAL MIXING: three files landed through three independent
    ``os.replace`` calls, so any one of them failing left three separate
    generations in one directory, and a reader trusting position over provenance
    would diff the current store against some earlier one and name paths from a
    generation nobody asked about. The generation swap makes that unrepresentable
    — the three files are written into one directory that becomes live in a
    single pointer replace, so the entries file beside a sidecar is always that
    sidecar's own.

    **What it still defends, which is why it stays.** Provenance is not proved by
    position even inside a published generation: a hand-restored, truncated or
    tampered ``entries.json`` still reaches this reader, and the alternative to
    refusing is a diff computed against a stat set that is not this pair's — a
    receipt that NAMES FILES an operator will go and investigate. A diagnostic
    that cannot prove which store it is describing must refuse and say so, never
    pass on partial knowledge. That is the same rule as ``core_sha256`` one file
    further out, and it now has the same shape of reason: both convict bytes that
    are not the ones this module wrote, rather than binding files the swap
    already binds.

    **SIZE, PRICED RATHER THAN DISCOVERED** (the C-7 class). Measured
    2026-08-18 by walking the operator's live ``agent-runtime`` tree read-only
    and serialising this exact payload: **22,286 entries → 3,539,812 bytes
    (3.38 MiB)**, i.e. **159 bytes per entry** against a mean path of 127
    characters. Projected at the 23,107-entry key the field logs: **~3.5 MiB**.

    That measurement also settles the format question P4 left open, in the
    opposite direction to the guess. JSON is not the cost: a compact
    ``path|mtime|size`` text form would spend ~153 bytes per entry against JSON's
    159 — a ~4 % saving — because the PATHS dominate and backslash escaping adds
    only ~10 bytes to each. A second, text-shaped atomic writer (which does not
    exist today) would therefore buy nothing worth its own authority. The lever
    that actually moves this number is the SIZE OF THE CLOSURE, not its encoding:
    18,804 of the field's 23,107 entries were ``deleted_archive/``, which no
    projection reads.

    **That is now done** (MC-8 / P12): the graveyard is excluded from the walk at
    ``_EXCLUDED_STORE_ENTRIES``, where the reader argument is written. The
    measurement above was taken BEFORE it, and is left standing because it is what
    justified the exclusion; read it as the pre-P12 number. Expected after: ~4,300
    entries and ~0.7 MiB here, with the same ~159 bytes per entry — the per-entry
    cost was never the lever and did not move.
    """

    return _live_generation_dir() / ENTRIES_FILENAME


def _core_digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
