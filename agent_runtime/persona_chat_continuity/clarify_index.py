"""The clarify-ticket index: open-ticket pointers by session, beside the tickets.

WHY THIS EXISTS. ``open_ticket_for_session`` is the tokenless-settlement
lookup and it runs on nearly EVERY mission-chat turn. Reading it as a glob
over the ticket directory made each turn pay for every question ever asked
inside the live TTL window — a per-turn cost that grows with a store that
is supposed to be write-rare. The index answers the same question in a
bounded number of file reads: one index file, then the newest candidate
ticket it names.

AUTHORITY AND SELF-HEALING. The index is a CACHE OF POINTERS, never a
second source of truth. Every token it hands back is re-read from its own
ticket file and re-verified (``state == open`` AND the record's own
``chat_session_id`` matches) before it can bind anything, so a stale,
hand-edited, or half-written entry can only ever produce a MISS — never a
wrong binding. Entries that fail that verification are dropped on the way
past, so the index converges without a repair pass.

THE MARKER FILE is what makes "no index file for this session" mean "no
open tickets" rather than "index lost". It is written LAST, after a full
rebuild from the ticket files themselves, so a crashed rebuild simply
leaves no marker and the next call redoes it (idempotent). Without it, a
session with no tickets — the overwhelmingly common case — could never be
told from a missing index and would fall back to the glob on every turn,
which is the cost this exists to retire.

THAT CLAIM IS RETRACTABLE, and must be. Being a cache saves this index
from every failure that leaves it with an entry too MANY — the read path
verifies those away. Nothing saves it from an entry too FEW, because the
marker is precisely what stops anyone from going and looking. So the two
writes that can lose a pointer take the claim back rather than keep it:
a failed add (:meth:`add`) and a rebuild racing a concurrent mint
(:meth:`rebuild`, which unions instead of replacing). One extra
rebuild is the price; a permanently invisible open ticket is not.

Composed out of ``PersonaChatClarifyTicketStore`` (lane B3, sheet
``persona_chat_continuity.md`` §2): the store holds one ``ClarifyTicketIndex``
and calls it; the ticket files stay the store's, and are the authority this
index only ever caches.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from .mint_receipts import _atomic_json

__layer__ = "stores"

#: The one ticket state the index points at (``clarify_tickets.CLARIFY_TICKET_OPEN``
#: re-exports this constant; one spelling).
CLARIFY_TICKET_OPEN = "open"


def expired(created_at: float, cutoff: float) -> bool:
    """THE expiry predicate, and there is deliberately only one.

    The ticket loop and the index sweep must agree EXACTLY about what
    "past its TTL" means, because the index sweep's entire safety argument
    is "every ticket this file names was already unlinked by the ticket
    loop". Two spellings of the comparison — or a second cutoff constant —
    make that argument true only by coincidence, and the day it stops being
    true the index file naming a LIVE ticket is the one deleted."""

    return created_at <= cutoff


class ClarifyTicketIndex:
    """A per-session pointer index over one ticket directory, with its own rebuild and sweep."""

    def __init__(
        self,
        ticket_root: Callable[[], Path],
        scan_records: Callable[[], tuple[list[dict[str, Any]], int]],
    ) -> None:
        self._ticket_root = ticket_root
        self._scan_records = scan_records

    def directory(self) -> Path:
        return self._ticket_root() / "by_session"

    def path(self, chat_session_id: str) -> Path:
        digest = hashlib.sha256(str(chat_session_id or "").encode("utf-8")).hexdigest()
        return self.directory() / f"{digest}.json"

    def state_path(self) -> Path:
        # Leading underscore, never a sha256 hex digest, so it cannot collide
        # with a per-session file.
        return self.directory() / "_index_state.json"

    def entries(self, chat_session_id: str) -> list[dict[str, Any]]:
        """The open-token pointers recorded for *chat_session_id*, newest first.

        "Could not read" collapses to "none recorded" here, which is the right
        answer for every caller that only READS the result — the lookup misses
        once and re-reads next turn, a cost it pays rather than a pointer it
        drops. It is the wrong answer for a caller about to write the list back,
        and that caller must use :meth:`read` instead."""

        return self.read(chat_session_id) or []

    def read(self, chat_session_id: str) -> list[dict[str, Any]] | None:
        """The recorded pointers, or ``None`` when the file could not be read.

        UNREADABLE IS NOT EMPTY, exactly as unreadable is not dead in
        :meth:`sweep`. A file that is simply absent legitimately means
        "no pointers recorded" and answers ``[]``; a file that IS there but
        would not read has told us nothing, and answering ``[]`` for it hands a
        read-modify-write caller a blank slate to overwrite live pointers with.
        The failure is the ordinary Windows one the add path already documents
        for its WRITE — an AV or indexer holding the file for the instant we
        touch it — not corruption, and not crash-only."""

        try:
            text = self.path(chat_session_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            # The one failure that IS an answer: nothing was ever recorded.
            return []
        except Exception:
            return None
        try:
            payload = json.loads(text)
        except Exception:
            return None
        raw = payload.get("open_tokens") if isinstance(payload, dict) else None
        entries = [
            {
                "clarify_token": str(item.get("clarify_token") or ""),
                "created_at": float(item.get("created_at") or 0.0),
            }
            for item in (raw if isinstance(raw, list) else [])
            if isinstance(item, dict) and item.get("clarify_token")
        ]
        entries.sort(key=lambda item: item["created_at"], reverse=True)
        return entries

    @staticmethod
    def payload(chat_session_id: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """The on-disk shape of one per-session index file. ONE writer of it.

        ``newest_created_at`` is the file's own record of the newest ticket it
        names, and it is what :meth:`sweep` reclaims by. Recording it
        here rather than inferring it from the filesystem is the point: an
        mtime is a property of the FILE, which any backup, restore, sync, or
        copy tool is free to rewrite without touching a byte of content, while
        this is a property of the DATA and travels with it.

        Written by :meth:`write` and :meth:`rebuild` alike, so
        the two cannot disagree about the shape — the drift that made the
        rebuild's hand-built dict a second spelling of this one.
        """

        ordered = sorted(entries, key=lambda item: item["created_at"], reverse=True)
        return {
            # v2 adds ``newest_created_at``. Purely additive: a v1 file still
            # reads correctly (the field's absence is DERIVED from the entries,
            # see :meth:`newest_created_at`), so there is no migration
            # pass and no rebuild owed.
            "schema_version": 2,
            "chat_session_id": str(chat_session_id),
            "newest_created_at": float(ordered[0]["created_at"]) if ordered else 0.0,
            "open_tokens": ordered,
        }

    def write(self, chat_session_id: str, entries: list[dict[str, Any]]) -> bool:
        """Record *entries* as the open pointers for *chat_session_id*.

        Returns ``False`` when they could not be recorded at all. Whether that
        is survivable depends entirely on the direction: a failed DROP leaves a
        pointer the read path verifies away anyway, a failed ADD loses one
        outright — see :meth:`add`."""

        path = self.path(chat_session_id)
        if not entries:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                return False
            return True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_json(path, self.payload(chat_session_id, entries))
        except OSError:
            return False
        return True

    def newest_created_at(self, path: Path) -> float | None:
        """The newest ticket ``created_at`` the index file at *path* names.

        ``None`` means the file could not be read — which is NOT the same
        answer as ``0.0`` and must never be treated as one: a transient read
        failure (the ordinary Windows AV/indexer case) would otherwise present
        a live index file as a dead one and have the sweep delete it, losing
        pointers the marker still swears are there.

        A ``schema_version`` 1 file predates the recorded field; the same fact
        is derivable from the entries it names, so those files answer honestly
        too and converge to v2 on their next write. Either way the answer comes
        from the file's CONTENT, never from its mtime.
        """

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            recorded = float(payload.get("newest_created_at") or 0.0)
        except (TypeError, ValueError):
            recorded = 0.0
        if recorded > 0.0:
            return recorded
        tokens = payload.get("open_tokens")
        newest = 0.0
        for item in tokens if isinstance(tokens, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                newest = max(newest, float(item.get("created_at") or 0.0))
            except (TypeError, ValueError):
                continue
        return newest

    def rebuild(self) -> bool:
        """Rebuild every per-session index from the ticket files. Idempotent.

        Runs once per store (on the first mint or lookup after this code
        arrives, and again after any crash that left no marker). The marker is
        written LAST so a partial rebuild is simply redone rather than trusted.

        REFUSES TO CLAIM COMPLETENESS when any ticket file will not decode. The
        marker this method writes is not a cache entry, it is the sentence "the
        index may be trusted as complete" (:meth:`ensure`), and it is
        PERMANENT — once written, every later lookup answers from the index and
        the full-scan fallback is never taken again. So a ticket skipped during
        the rebuild is not skipped once, it is skipped forever: the tokenless
        settlement stops finding it, the turn that would have closed it opens a
        second ticket for the same question, and no later pass can recover it
        because nothing will ever rebuild again. Since the skip is usually a
        transient hold on a file that reads fine a second later, that is a
        permanent hole punched by a momentary failure.

        Returning ``False`` is not a new failure mode — it is the one this
        method already has, and its contract is exactly right here: the caller
        falls back to the full scan, which reads the store directly and is
        correct by construction. The store keeps working, unindexed, until the
        unreadable file is repaired or removed; correctness never depended on
        the index existing.
        """

        records, unreadable = self._scan_records()
        if unreadable:
            return False
        by_session: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if record.get("state") != CLARIFY_TICKET_OPEN:
                continue
            root = str(record.get("chat_session_id") or "")
            token = str(record.get("clarify_token") or "")
            if not root or not token:
                continue
            by_session.setdefault(root, []).append(
                {"clarify_token": token, "created_at": float(record.get("created_at") or 0.0)}
            )
        try:
            self.directory().mkdir(parents=True, exist_ok=True)
            for root, entries in by_session.items():
                # UNION with what is already recorded, never a replacement. The
                # scan above is a SNAPSHOT, and a mint that lands after it but
                # before this write would otherwise have its pointer overwritten
                # by the pre-mint view — and lost for good, because the marker
                # written below then stops any later rebuild from recovering it.
                # That is not merely a miss: the lookup goes on answering with an
                # OLDER open ticket that the pre-index glob would never have
                # returned, so the tokenless settlement closes the wrong
                # question. A union can only ever ADD a pointer, and one the
                # ticket files do not back is dropped on the read path like every
                # other stale entry — the same verification that makes this
                # index a cache and not an authority.
                merged = {entry["clarify_token"]: entry for entry in entries}
                for entry in self.entries(root):
                    merged.setdefault(entry["clarify_token"], entry)
                _atomic_json(
                    self.path(root),
                    self.payload(root, list(merged.values())),
                )
            _atomic_json(
                self.state_path(), {"schema_version": 1, "rebuilt_at": time.time()}
            )
        except OSError:
            return False
        return True

    def ensure(self) -> bool:
        """``True`` when the by-session index may be trusted as complete.

        ``False`` means the caller must fall back to the scan — correctness
        never depends on the index being present."""

        try:
            if self.state_path().exists():
                return True
        except OSError:
            return False
        return self.rebuild()

    def invalidate(self) -> None:
        """Retract the completeness claim, forcing ONE rebuild on the next read.

        The marker is the whole reason "no index file for this session" may be
        read as "no open tickets". Anything that leaves that claim false has to
        take the claim back, or the index goes on answering a question it can no
        longer answer."""

        try:
            self.state_path().unlink(missing_ok=True)
        except OSError:  # pragma: no cover - defensive; the ticket is what matters
            pass

    def add(self, chat_session_id: str, token: str, created_at: float) -> None:
        entries = self.read(chat_session_id)
        if entries is None:
            # A READ WE COULD NOT MAKE IS NOT AN EMPTY INDEX, and this is the
            # one caller where the difference costs a ticket: the list is about
            # to be written back WHOLESALE, so treating an unreadable file as
            # "nothing recorded" replaces every pointer it held with just this
            # one — while the marker goes on swearing the index is complete, so
            # the tokenless settlement never looks for the others again and
            # nothing rebuilds. Same silent permanent miss as a swallowed add,
            # same answer: retract the claim and let ONE rebuild re-derive every
            # pointer from the ticket files, which are the authority the index
            # only ever cached. Deliberately no write — a list we know is
            # missing entries is not a better record than the one on disk.
            self.invalidate()
            return
        if any(entry["clarify_token"] == token for entry in entries):
            return
        entries.append({"clarify_token": token, "created_at": float(created_at)})
        entries.sort(key=lambda item: item["created_at"], reverse=True)
        if not self.write(chat_session_id, entries):
            # A SWALLOWED ADD IS A SILENT PERMANENT MISS. The ticket is on disk
            # and open, the marker still swears the index is complete, so the
            # tokenless settlement never looks for it again and nothing ever
            # rebuilds — and the loss lands squarely on the one number the
            # adoption readout exists to report. A transient replace failure is
            # not exotic on Windows (an AV or indexer holding the target is the
            # ordinary case), so this cannot be reasoned away as crash-only.
            # Retracting the marker turns it into ONE extra rebuild on the next
            # lookup, which re-derives the pointer from the ticket file that IS
            # there. The marker exists so the scan is not paid ROUTINELY, not so
            # it is never paid at all.
            self.invalidate()

    def drop(self, chat_session_id: str, token: str) -> None:
        entries = self.entries(chat_session_id)
        remaining = [entry for entry in entries if entry["clarify_token"] != token]
        if len(remaining) != len(entries):
            # A failed drop is survivable and deliberately NOT invalidating: the
            # entry it left behind names a settled ticket, which the read path
            # re-verifies and discards. Only a lost ADD costs a ticket.
            self.write(chat_session_id, remaining)

    def sweep(self, cutoff: float) -> None:
        """Drop index files that cannot name a live ticket any more.

        BY THE FILE'S OWN RECORD of the newest ticket it names, against the
        SAME cutoff the ticket loop above just used. That is the whole safety
        argument: if every token in the file is expired, the loop already
        unlinked all of them, so the file can only name the dead.

        It used to be by MTIME, which is the same argument resting on an
        INFERRED invariant — "the filesystem's clock tracks this file's
        content" — that nothing in the code enforces and that any backup,
        restore, sync, or copy tool breaks silently. Both directions of that
        break are real, and one of them is not survivable: a restored file
        carrying a fresh mtime over stale content merely leaks (the file is
        inert; entries verify away on the read path), but a copy that lands
        stale mtimes on LIVE content gets the file deleted while the marker
        goes on swearing the index is complete — the silent permanent miss
        this store already fixed once, arriving through the back door.
        ``created_at`` is a property of the DATA and travels with it.

        Deliberately NOT a read-modify-write per pruned ticket: that would race
        a concurrent mint on the same session and could clobber a live pointer.
        Entries for individually-pruned tickets self-heal on the read path
        instead."""

        try:
            entries = list(self.directory().glob("*.json"))
        except OSError:
            return
        state_path = self.state_path()
        for entry in entries:
            if entry == state_path:
                continue
            newest = self.newest_created_at(entry)
            # UNREADABLE IS NOT DEAD. A file we could not read has not been
            # proven to name only expired tickets, and the sweep only ever
            # deletes on proof: keeping an inert file costs one small file,
            # deleting a live one costs a ticket nothing will look for again.
            if newest is None or not expired(newest, cutoff):
                continue
            try:
                entry.unlink(missing_ok=True)
            except OSError:
                continue

    def lookup(
        self, root: str, resolve: Callable[[str], dict[str, Any] | None]
    ) -> dict[str, Any] | None:
        """The newest OPEN ticket the index names for *root*, re-verified.

        The index is never trusted on its own: every token it offers is re-read
        through *resolve* and re-verified against its own record, so the worst a
        stale entry can do is cost one wasted read and get itself dropped."""

        entries = self.entries(root)
        stale = 0
        for entry in entries:
            record = resolve(entry["clarify_token"])
            if (
                record is None
                or record.get("state") != CLARIFY_TICKET_OPEN
                or str(record.get("chat_session_id") or "") != root
            ):
                stale += 1
                continue
            # Stop at the first live ticket: the entries are newest-first, so
            # this IS the answer, and reading past it would trade the O(1) the
            # index exists for. Anything stale BEHIND it is dropped when it in
            # turn becomes the head, or by the sweep.
            if stale:
                self.write(root, entries[stale:])
            return record
        if stale:
            self.write(root, [])
        return None
