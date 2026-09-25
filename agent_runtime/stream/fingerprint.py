"""The watchdog's scope fingerprint (Stage 12 backstop): a cheap stat of the
state whose writers emit no EventLog event, taken once per drain pass by
``session.StreamSession`` — split by store family (pointers and catalogs, the
chat SessionDB, the ``running_work`` stores)."""

from __future__ import annotations

import hashlib

from .. import paths
from ..core_cache.walk import sqlite_fingerprint_triples

__layer__ = "stores"


def _scope_fingerprint() -> str:
    """Cheap mtime/size fingerprint of scope/catalog state (Stage 12 backstop).

    Covers exactly the state whose writers have historically slipped the
    event rule or sit outside ``agent_runtime/store/``: the active-scope
    pointer files, the workspace/realm/persona stores, the blueprint
    catalog, and the head-home SessionDB. Evented, high-churn stores
    (tasks/runs/proofs/incidents) are guarded by the store/event CI
    invariant instead — fingerprinting them here would only mask violations
    that test already prevents.

    The SessionDB matters because the persona-chat directory (Chat History)
    is derived from it and its writers emit no EventLog events: with the S6
    patch lane on, a chat-session mint never appears in any patch frame, so
    watermark-gated consumers kept their hydrate-time chat list for the
    stream's whole lifetime (live incident 2026-07-25: the Launcher's Chat
    History froze for ~36h until a restart re-hydrated). The per-session
    turn-element files are deliberately NOT statted here: element flushes
    land many times per second during a streaming turn and would make the
    watchdog append a reconcile (= one full-core delta) every heartbeat.

    The ``running_work`` durable stores (``processes.json`` + the
    background-work ``state.db``) are the same class as the SessionDB: a
    background process starting or exiting rewrites the checkpoint, and a
    delegation dispatch/finalize writes ``async_delegations`` — with NO
    EventLog event either way. The serve read-model cache adopted them on
    2026-08-03 (``_runtime_state_fingerprint``); this backstop did not, so a
    stream consumer rendered the last pre-exit ``running_work`` row forever
    (live incident 2026-08-11: a 20-second terminal task showed
    "Terminal · running" in the Launcher's Activity panel minutes after the
    durable side had settled). Resolved through the writers' own path
    authority, ``running_work_store_paths`` — never a second path list free
    to drift. Note the background-work ``state.db`` can be a DIFFERENT file
    from the chat SessionDB statted above: the chat scope consults a durable
    head-home pointer the background-work writers do not.

    Both SQLite stores are keyed through ``core_cache.sqlite_fingerprint_triples``
    — the same masked triple the boot-cache lane keys them by — and NOT by a raw
    stat of the three siblings, which is what this function did until
    2026-08-21. The mask collapses "no ``-wal`` on disk" and "a zero-length
    ``-wal`` on disk" into one triple, because SQLite deletes the WAL on a clean
    last-close and re-creates it EMPTY on the next open: the difference between
    those two states is the lifetime of somebody's connection, never content.
    Under the raw stat a poll landing while any process merely HELD the database
    open read a fresh ``mtime_ns``, and a poll landing at rest read ``absent`` —
    so a database nobody was writing flapped the fingerprint twice per open, and
    each flap costs one synthetic ``state.reconciled``, which ``patch_coverage``
    classifies UNCOVERED, which demotes the whole batch to a full core rebuild.
    Measured on the operator's runtime over the 22.16 h to 2026-08-21 09:06:
    2 433 ``snapshot_build reason=demote`` against 35 hydrates (median build_ms
    3 083, max 37 266 — 2.29 h of CPU), and 1 239 ``state.reconciled`` — 96.9 %
    of every event appended in the window — at a median 9.0 s spacing, i.e. the
    watchdog reconciling on roughly every other heartbeat, indefinitely, with
    nothing to reconcile. 3 338 distinct fingerprints over 4 597 reconciles
    against a recurring at-rest anchor is that flip's signature and not a
    write's: real writes do not come back to the same value.

    The narrowing is a NARROWING, not a disabling, and the line it holds is the
    same one the turn-element exclusion above holds. A committed write still
    moves this fingerprint within one poll, by one of two paths that SQLite's
    durability rules leave no gap between: uncheckpointed, the ``-wal`` sibling
    is non-empty and is keyed in full (mask suspended); checkpointed, the frames
    are in ``state.db``, whose own mtime and size are the FIRST triple here. So
    the ≤2×heartbeat staleness SLO that 2026-07-25 and 2026-08-11 bought is
    intact — ``test_scope_fingerprint_covers_head_home_session_db`` and
    ``test_scope_fingerprint_covers_running_work_stores`` still pin those two
    incidents, and ``test_scope_fingerprint_moves_on_committed_chat_write``
    pins the direction a constant fingerprint would trivially break.

    ``PRAGMA data_version`` was evaluated first and REJECTED, recorded here so
    it is not re-proposed as the obvious answer it looks like. Measured on
    SQLite 3.45.3: (a) its value is only comparable WITHIN one connection — a
    fresh connection per poll, which is the only shape a stateless fingerprint
    can take, returns a constant and detects nothing; (b) making it work
    therefore means the stream process holding a SessionDB connection open for
    its whole lifetime, which is the exact shape of MCF-27 (every full snapshot
    build leaked a chat SessionDB connection) two days after that was found;
    (c) it is NOT checkpoint-immune as its reputation suggests — a
    ``wal_checkpoint(TRUNCATE)`` with no data change bumps it, so it does not
    even buy a clean answer for the case the mask leaves uncovered; and (d) it
    buys nothing here anyway. Scenario-by-scenario against this mask — read-only
    open/close, write-capable open/close with no write, WAL creation, WAL
    deletion, ``utime`` on the WAL, uncommitted write, rollback, PASSIVE
    checkpoint, committed write from another PROCESS — the two agree on every
    state except the PASSIVE checkpoint, which cannot occur without a preceding
    commit that both already reported.
    """

    parts = [*_pointer_and_catalog_parts(), *_chat_db_parts(), *_running_work_parts()]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _pointer_and_catalog_parts() -> list[str]:
    """The active-scope pointer files and the workspace / realm / agent catalogs."""

    parts: list[str] = []
    for path in (paths.active_realm_path(), paths.active_workspace_path()):
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            parts.append(f"{path.name}:absent")
    directories = [paths.workspaces_dir(), paths.realms_dir(), paths.agents_dir()]
    for directory in directories:
        try:
            entries = [
                entry
                for pattern in ("*.json", "*.yaml", "*.yml")
                for entry in directory.glob(pattern)
            ]
        except OSError:
            continue
        for entry in sorted(entries):
            try:
                stat = entry.stat()
                parts.append(f"{entry.name}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                continue
    return parts


def _chat_db_parts() -> list[str]:
    """The head-home chat SessionDB, keyed through the shared masked triples."""

    try:
        from ..chat_session_scope import chat_session_db_path

        db_path = chat_session_db_path()
        return [
            f"{db_path.name}{suffix}:{mtime_ns}:{size}"
            for suffix, mtime_ns, size in sqlite_fingerprint_triples(db_path)
        ]
    except Exception:  # noqa: BLE001 — chat persistence absence is itself stable
        return ["session_db:unresolved"]


def _running_work_parts() -> list[str]:
    """The ``running_work`` durable stores, through the writers' own path authority."""

    parts: list[str] = []
    try:
        from ..running_work.ownership import running_work_store_paths

        store_paths = running_work_store_paths()
        if not store_paths:
            # An empty tuple means "the home could not be resolved", not
            # "nothing to watch" — same sentinel rule as the serve cache: the
            # part is stable, so an unresolvable home never flaps the
            # fingerprint, but the absence is recorded rather than silent.
            parts.append("running_work_stores:unresolved")
        for store_path in store_paths:
            # The checkpoint is plain JSON; the delegation store is SQLite,
            # whose mutations can land in the WAL without moving the main
            # file's mtime — key the siblings through the shared authority like
            # the chat DB above.
            if store_path.suffix == ".db":
                parts.extend(
                    f"bgwork:{store_path.name}{suffix}:{mtime_ns}:{size}"
                    for suffix, mtime_ns, size in sqlite_fingerprint_triples(store_path)
                )
                continue
            try:
                stat = store_path.stat()
                parts.append(
                    f"bgwork:{store_path.name}:{stat.st_mtime_ns}:{stat.st_size}"
                )
            except OSError:
                parts.append(f"bgwork:{store_path.name}:absent")
    except Exception:  # noqa: BLE001 — same posture as the chat DB above
        parts.append("running_work_stores:unresolved")
    return parts
