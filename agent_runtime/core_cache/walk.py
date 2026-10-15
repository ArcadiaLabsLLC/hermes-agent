"""The stat walker: one entry per path, the tree walk with its exclusions, the
SQLite WAL/content rules and the content-keyed config inputs.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from agent_runtime.core_cache.vocabulary import (
    RECEIPT_FINGERPRINT_REFUSED,
    REFUSAL_ENTRIES_EXCEEDED,
    _DB_SIBLINGS,
    _DIR_MARK,
    _TMP_SUFFIX,
    _WAL_SIBLING,
    logger,
)
from agent_runtime.core_cache.models import FingerprintEntry

__layer__ = "stores"

__all__ = [
    "_CONFIG_CONTENT_MAX_BYTES",
    "_config_input_entry",
    "_config_input_is_content_keyed",
    "_db_entries",
    "_entry_triple",
    "_receipt_fingerprint_refused",
    "_stat_entry",
    "_wal_without_frames_is_content_free",
    "_walk_tree",
    "sqlite_fingerprint_triples",
]


def _stat_entry(path: Any) -> FingerprintEntry:
    """One (path, mtime_ns, size) triple. An ABSENT path is a stable signal.

    A missing file records ``-1/-1`` rather than being skipped: "this input does
    not exist" is a fact the next build must be able to disagree with. Skipping
    it would make an appearing file indistinguishable from an unchanged one.

    A DIRECTORY records ``_DIR_MARK`` for both numbers — see that constant for
    why its mtime is poison rather than signal.
    """

    text = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return FingerprintEntry(text, -1, -1)
    if stat.S_ISDIR(st.st_mode):
        return FingerprintEntry(text, _DIR_MARK, _DIR_MARK)
    return FingerprintEntry(text, int(st.st_mtime_ns), int(st.st_size))


def _entry_triple(entry: os.DirEntry, is_dir: bool) -> FingerprintEntry:
    if is_dir:
        return FingerprintEntry(entry.path, _DIR_MARK, _DIR_MARK)
    try:
        st = entry.stat()
    except OSError:
        return FingerprintEntry(entry.path, -1, -1)
    return FingerprintEntry(entry.path, int(st.st_mtime_ns), int(st.st_size))


def _walk_tree(
    root: Path,
    out: list[FingerprintEntry],
    *,
    limit: int,
    exclude_top: frozenset[str] = frozenset(),
    exclude_nested: Mapping[str, frozenset[str]] = MappingProxyType({}),
) -> bool:
    """Enumerate ``root`` and every descendant, bounded by ``limit``.

    Returns False when the bound was reached — the caller must then refuse to
    fingerprint at all rather than serve a truncated stat set.

    TWO EXCLUSION SHAPES, and they are not interchangeable:

    * ``exclude_top`` filters ``root``'s OWN entries by name and nothing deeper.
      That is what makes it safe to name a directory the store root can only hold
      one of (see :data:`_EXCLUDED_STORE_ENTRIES`);
    * ``exclude_nested`` maps a top-level entry name to the child names skipped
      anywhere INSIDE that entry's subtree. It exists for the one case where the
      unread tree sits at depth >= 2 (``realm_sync/<server>/.git`` — see
      :data:`_EXCLUDED_NESTED_STORE_NAMES` for the reader audit and the removal
      obligation). The skip-set travels DOWN with the subtree it was declared
      for, so it can never reach a sibling: a nested exclusion must name both the
      subtree it applies inside and the child it skips, which is exactly what a
      blanket name filter at every depth would not.

    Every FILE contributes (path, mtime_ns, size); every DIRECTORY contributes
    its path alone. Files individually rather than by their parent's mtime
    because replacing an existing entry does not move the containing directory
    on NTFS (the in-place-rewrite case the boards-tree per-card stat pattern
    already exists for); directories by path alone for the reason at
    :data:`_DIR_MARK`.

    Symlinked directories ARE followed, and the choice is deliberate: treating
    one as a leaf would leave everything under it outside the closure, which is
    the failure mode that matters here. A symlink LOOP is therefore possible and
    is handled by the bound rather than by loop detection — hitting ``limit``
    refuses the whole fingerprint, and refusing means "never cache", which is
    safe. Detecting the loop and continuing would not be: it would produce a
    plausible key over an incomplete walk.

    That doctrine is UNCHANGED by ML-10 and is kept deliberately (A5). What
    changed is only that the caller's refusal now leaves a countable receipt
    naming the tree — :func:`_receipt_fingerprint_refused` — so a loop that
    disables the cache for a whole install is a census row rather than one
    WARNING sentence somebody has to already be reading.
    """

    # The tree root records its PATH only, never its existence-or-not: a root
    # that appears because the cache wrote its own directory into it (the store
    # root's first-ever write on a virgin install) must not flip the key, and a
    # root that genuinely gains content flips it through the content's own
    # triples.
    out.append(FingerprintEntry(str(root), _DIR_MARK, _DIR_MARK))
    try:
        top_level = sorted(os.scandir(root), key=lambda entry: entry.name)
    except OSError:
        # An unreadable root is itself a stable signal (recorded above). It is
        # NOT a bound failure: a store root that does not exist yet is the
        # ordinary cold-start shape.
        return True
    # Each pending item carries the nested skip-set of the top-level subtree it
    # came from — an empty set for the top-level entries themselves, so a subtree
    # can never be filtered by its own declaration, and the declared set for
    # everything below one. Carrying it on the item rather than re-deriving it
    # from the path is what keeps the rule "inside THIS subtree" instead of
    # "anywhere whose path happens to contain that name".
    # Each pending item carries the nested skip-set of the top-level subtree it
    # belongs to. ``exclude_nested`` is consulted HERE and only here — over
    # ``root``'s own entry names — so a directory that merely shares a declared
    # top-level name while nested somewhere else can never activate the rule.
    # The set then travels DOWN with the subtree and filters its descendants at
    # push time, which is also why a subtree is never filtered by its own
    # declaration: ``realm_sync`` is not inside ``realm_sync``.
    pending: list[tuple[os.DirEntry, frozenset[str]]] = []
    for entry in top_level:
        if entry.name in exclude_top:
            continue
        pending.append((entry, exclude_nested.get(entry.name, frozenset())))
    while pending:
        if len(out) >= limit:
            return False
        entry, skip_nested = pending.pop()
        name = entry.name
        if name.endswith(_TMP_SUFFIX) and name.startswith("."):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            is_dir = False
        out.append(_entry_triple(entry, is_dir))
        if not is_dir:
            continue
        try:
            children = sorted(os.scandir(entry.path), key=lambda item: item.name)
        except OSError:
            continue
        pending.extend(
            (item, skip_nested) for item in children if item.name not in skip_nested
        )
    return len(out) < limit


def _wal_without_frames_is_content_free(entry: FingerprintEntry) -> FingerprintEntry:
    """A WAL with no frames keys as ``(path, 0, 0)`` — ABSENT OR EMPTY, one triple.

    The one line where "the build reads this database" stops being spelled the
    same way as "somebody wrote to this database". See :data:`_DB_SIBLINGS` for
    the ground under the mask.

    WHY ABSENT AND EMPTY ARE ONE FACT
    =================================

    SQLite deletes the WAL when the last connection closes cleanly, and
    re-creates it at zero length on the next open. So a quiescent database
    alternates between "no ``-wal`` on disk" and "a zero-length ``-wal`` on
    disk" for reasons that are entirely about CONNECTION LIFETIME and never
    about content: both states say *no uncheckpointed frames*, which is the only
    thing this sibling is stat'd to tell us. Keying them apart records the
    lifecycle of a reader as if it were a write.

    This does NOT generalise, and the distinction it drops is real everywhere
    else. :func:`_stat_entry` records a missing input as ``-1/-1`` precisely so
    that a file which APPEARS is not indistinguishable from one that never
    moved — an appearing config, an appearing store row, an appearing skill
    package are all content events. The WAL is the one input whose appearance is
    definitionally content-free, because it appears EMPTY: the appearance and
    the emptiness are the same open() call. The moment it carries a frame its
    size is non-zero and it is keyed like anything else, so the general rule is
    suspended only over the exact state in which it says nothing.

    (A DIRECTORY at this path — ``_DIR_MARK``, not a state SQLite can produce —
    collapses here too. A database whose WAL path is a directory cannot be
    opened at all, and would fail loudly at the open long before a stale key
    could matter.)

    WHAT THE FIELD SHOWED, AND THE CONSEQUENCE THAT WILL BE FORGOTTEN
    ================================================================

    Measured on the operator's machine, 2026-08-18: two boots recorded the SAME
    events offset and the SAME entry count, and the second demoted
    ``fingerprint_mismatch`` anyway. ``state.db-wal``'s NTFS creation time was
    4.15 s AFTER the consult that missed — boot A's clean exit had deleted it,
    boot B had not yet opened the database — while the sidecar, written
    mid-session by a later build, held it present-and-empty. One entry flipped;
    nothing else in the closure moved.

    The structural consequence is worse than the flip: **which of the two states
    the sidecar records depends on which build in the process wrote LAST.** A
    boot whose only build is the boot build writes a consult-time key (WAL
    absent, because the database has not been opened yet) and the next boot can
    match. Any later led build — the launcher's hydrate, any ``forceFresh``
    gesture — writes a mid-session key (WAL present) and the next boot is a
    GUARANTEED miss. That is deterministic given the build history, not a race.

    Perverse corollary, stated because it will mislead the first person who
    tests this: **a hard-killed serve leaves the WAL behind and converges; a
    clean exit deletes it and misses.** Under this mask neither shape is keyed
    differently from the other, which is the point.
    """

    if entry.size > 0:
        return entry
    return FingerprintEntry(entry.path, 0, 0)


#: Ceiling on a config input this module is willing to READ rather than stat.
#:
#: Every path routed through :func:`_config_input_entry` is hand-authored YAML —
#: the operator's live one is 23 KB, the base seed 8 KB — so a megabyte is three
#: orders of magnitude of headroom and still a hard stop. Over it the entry
#: keeps its ordinary mtime triple: a config that large is not the class this
#: mask was measured against, and reading an unbounded file on the boot path to
#: decide a cache key would trade one demote for a worse cost.
_CONFIG_CONTENT_MAX_BYTES = 1 << 20


def _config_input_is_content_keyed(entry: FingerprintEntry) -> FingerprintEntry:
    """A hand-authored YAML config keys on its CONTENT, never on its mtime.

    Second member of the same family as
    :func:`_wal_without_frames_is_content_free`, and the same shape: one input
    class whose stat triple moves for reasons that are NOT content, masked at
    the one line where it enters the closure, with the measurement written down
    so the next person does not have to re-earn it.

    WHAT WAS MEASURED (operator's runtime, 2026-08-21)
    =================================================

    Every Mission Control boot demoted with::

        reason=fingerprint_mismatch inputs=2225 changed=1
        diff=X:\\Eternia\\.hermes\\profiles\\alice\\config.yaml

    and paid a full rebuild — 6,467 ms on the 13:17 boot, of which
    ``agents_readiness`` was 3,266 ms. The named file's mtime was minutes old on
    each miss and its NTFS creation time moved with it, i.e. the file is
    ATOMICALLY REPLACED (temp + ``os.replace``), not appended to.

    The convicting measurement is not the mtime. It is that
    ``profiles/alice/config.yaml`` was, at the moment of the miss, **byte-for-byte
    identical to a copy taken two days earlier** — same 23,255 bytes, same
    SHA-256 — while its mtime had moved repeatedly in between. So the writer
    re-serialises the document and lands the same bytes; the mtime triple
    reports a change that does not exist, and the persisted core is thrown away
    for it.

    WHY THIS IS THE LAYER, AND NOT "STOP THE WRITE"
    ==============================================

    Stopping the needless write is the narrower fix and would be preferable IF
    the writer were on this repo's boot path. It is not, and that was
    established by instrumentation rather than by reading: a tracer on
    ``os.replace`` / ``os.rename`` / ``open(w)`` / ``Path.write_*`` / ``os.utime``
    / ``shutil.copyfile`` around a real ``build_snapshot()`` — and around
    ``harness snapshot|status|agents|personas|doctor|chats|board|office``,
    ``profile list``, ``auth status``, ``config get`` and ``doctor``, each in a
    sandboxed home seeded with a structural copy of the operator's own config —
    recorded ZERO writes to any ``config.yaml``. On the live machine the 13:51
    boot demoted naming the same file while that file's mtime did not move
    during the boot at all. The rewrite is real, repeated, and OUTSIDE the
    snapshot build.

    A cache that can be invalidated by any writer anywhere re-writing a byte
    for byte identical document is a cache with no floor. Keying the class on
    content gives it one, and does so for every future writer of these four
    files rather than for the one that happened to be caught.

    WHAT IS DELIBERATELY NOT WEAKENED
    =================================

    * **A genuine edit still invalidates.** The digest is over the bytes, so any
      content change flips the key — including one that leaves ``size``
      unchanged, which the mtime triple could only catch by timestamp.
    * **Appearance and disappearance still count.** An absent path keeps
      :func:`_stat_entry`'s ``-1/-1`` and a directory keeps ``_DIR_MARK``;
      neither is read, so the "an appearing config is a content event" rule that
      :func:`_wal_without_frames_is_content_free` explicitly refuses to
      generalise away is untouched here too.
    * **The class is four CALL SITES, named where they enter the closure.** Per
      profile ``config.yaml`` and ``profile.yaml`` (class 4), plus the pinned
      ambient config authority and the harness root config (class 5). Nothing
      else in this module reaches the mask. NOT the ``active_profile`` pointer (written
      only by an explicit profile switch, and its whole content is the switch),
      NOT the store subtree, NOT the skill roots — those are walked, unbounded,
      and hashing them would be the expensive shape this mask is careful not to
      become.

    COST, MEASURED rather than asserted: one bounded read per entry, so
    ``2 * <profiles> + 2`` reads — 22 files on the operator's ten-profile home.
    Benchmarked at the live file size (23,255 B), 20 warm passes: the same 22
    paths cost a median **1.3 ms** stat-only and **9.9 ms** content-keyed, i.e.
    **+8.6 ms** per fingerprint. That buys back a 6,467 ms rebuild on every boot
    that would otherwise demote, and it is small beside the 2,225-entry stat
    closure the same pass already walks. If a home ever grows profiles by an
    order of magnitude this is the number to re-measure.

    A read that fails (permissions, a mount that went away mid-pass) falls back
    to the stat triple rather than refusing: degrading to today's behaviour for
    one entry is strictly better than refusing to fingerprint the whole install.
    """

    if entry.size < 0 or entry.mtime_ns == _DIR_MARK:
        # Absent, or a directory. Both are already content-free and stable.
        return entry
    if entry.size > _CONFIG_CONTENT_MAX_BYTES:
        return entry
    try:
        with open(entry.path, "rb") as handle:
            body = handle.read(_CONFIG_CONTENT_MAX_BYTES + 1)
    except OSError:
        return entry
    if len(body) > _CONFIG_CONTENT_MAX_BYTES:
        return entry
    # The leading bits of the same digest the fingerprint itself is built from,
    # taken as a NON-NEGATIVE, SIGNED-64-REPRESENTABLE int. Two constraints, both
    # deliberate:
    #
    # * non-negative, so it can never collide with ``-1`` (absent) or
    #   ``_DIR_MARK`` (-2) — the two sentinels this field already carries;
    # * 63 bits and no more, because this value is persisted verbatim into
    #   ``entries.json`` (:func:`_entries_payload`) as a JSON number. Nothing
    #   outside Python reads that file today, and a bignum would be correct if
    #   one never did — but a fingerprint entry is not the place to plant a
    #   value the next consumer's integer type cannot hold. 63 bits over a
    #   two-dozen-entry class is collision-free for every practical purpose;
    #   a collision would cost one stale serve of one config, not corruption.
    keyed = int.from_bytes(hashlib.sha256(body).digest()[:8], "big") >> 1
    return FingerprintEntry(entry.path, keyed, entry.size)


def _config_input_entry(path: Any) -> FingerprintEntry:
    """:func:`_stat_entry` for a config input, under the content mask above."""

    return _config_input_is_content_keyed(_stat_entry(path))


def sqlite_fingerprint_triples(db_path: Any) -> tuple[tuple[str, int, int], ...]:
    """``(suffix, mtime_ns, size)`` per journal sibling, under the WAL mask.

    THE one authority for "how does a poll lane key a SQLite database", promoted
    out of this module on 2026-08-21 because it had exactly one caller and three
    lanes needed it. The other two keyed the same database by a raw stat triple
    over the same three siblings, so the connection-lifetime flip
    :func:`_wal_without_frames_is_content_free` was written to absorb — WAL
    absent after a clean last-close, WAL present-and-empty the moment anything
    opens the file — reached them undiminished:

    * ``stream._scope_fingerprint`` (the Stage 12 watchdog, ~5 s cadence). Each
      flip appended a synthetic ``state.reconciled``, which ``patch_coverage``
      classifies UNCOVERED, which demotes the batch to a full core rebuild.
      Measured on the operator's runtime over 22.16 h to 2026-08-21 09:06:
      **2 433 ``snapshot_build reason=demote`` against 35 hydrates, median
      build_ms 3 083, max 37 266 — 2.29 h of CPU**, while the event log took
      1 239 ``state.reconciled`` (96.9 % of all events in the window) at a
      median 9.0 s spacing. 3 338 DISTINCT fingerprints over 4 597 reconciles,
      against a recurring at-rest anchor: the signature of one entry alternating
      between a stable "absent" string and a fresh ``mtime_ns`` on every open.
    * ``harness_parts.serve.boot._runtime_state_fingerprint`` (the read-model cache),
      where the same flip keeps the cache permanently cold — the defect a
      2026-08-09 analysis named and nobody propagated the mask to.

    Returned keyed by SUFFIX rather than by path so a caller can spell its own
    label (the stream lane keys by basename, the cache lane by full path)
    without a second stat list free to drift from :data:`_DB_SIBLINGS`.
    """

    text = str(db_path)
    triples: list[tuple[str, int, int]] = []
    for suffix in _DB_SIBLINGS:
        entry = _stat_entry(text + suffix)
        if suffix == _WAL_SIBLING:
            entry = _wal_without_frames_is_content_free(entry)
        triples.append((suffix, entry.mtime_ns, entry.size))
    return tuple(triples)


def _db_entries(db_path: Any, out: list[FingerprintEntry]) -> None:
    text = str(db_path)
    for suffix, mtime_ns, size in sqlite_fingerprint_triples(db_path):
        out.append(FingerprintEntry(text + suffix, mtime_ns, size))


def _receipt_fingerprint_refused(*, scope: str, root: Any, bound: int) -> None:
    """The countable artifact for a walk that hit its entry bound (A4).

    A bound refusal disables the cache for the whole install — every boot pays
    the full build, forever, and the only thing that said so was a WARNING
    sentence that did not even name which store root blew the bound. This is the
    same fact on the same channel the shadow lane reports divergence on, in the
    shape a census can count: ``reason`` types it, ``scope`` says WHICH walk
    refused (the two bounds are different numbers over different trees),
    ``root`` names the tree to go look at, ``bound`` says what it was measured
    against.

    **The refusal itself is untouched and stays untouched.** Reaching a bound
    still makes the fingerprint ``None``, and ``None`` still means never cache —
    see :func:`build_input_fingerprint`. This function adds a receipt and decides
    nothing.
    """

    logger.warning(
        "snapshot_core_cache %s reason=%s scope=%s bound=%d root=%s — the walk "
        "hit its bound, so the stat set would have been truncated; the "
        "fingerprint is refused outright and nothing may be served from the "
        "cache until the tree named here shrinks or the bound is re-measured. A "
        "truncated stat set is exactly a missed input.",
        RECEIPT_FINGERPRINT_REFUSED,
        REFUSAL_ENTRIES_EXCEEDED,
        scope,
        bound,
        root,
    )
