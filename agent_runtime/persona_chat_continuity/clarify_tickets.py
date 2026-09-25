"""Clarify tickets: bind a clarify ANSWER to the thread its QUESTION was asked in."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterator

from .. import paths
from ..serde import safe_assignment_text, safe_assignment_token

from .mint_receipts import _atomic_json

__layer__ = "stores"


#: How long a clarify ticket file is kept before the sweep may prune it. TTL
#: governs GARBAGE COLLECTION ONLY — an expired-but-present ticket still binds
#: (see :class:`PersonaChatClarifyTicketStore`). One rule, no cliff.
CLARIFY_TICKET_TTL_SECONDS = 604_800  # 7 days

#: ``clarify-<12 hex>`` — mirrors the relay id precedent
#: (``agent-relay-<12 hex>``, ``tools/agent_chat_tool.py``). 48 bits is ample:
#: the token is a LOOKUP KEY validated against a stored record, never a
#: capability secret. The session it resolves to is independently re-validated
#: by the handler's existing ``unknown_chat_session`` / ``foreign_chat_session``
#: guards, so guessing a token buys nothing a caller could not already name.
CLARIFY_TOKEN_PREFIX = "clarify-"

#: Ticket lifecycle states. ``open`` → the question is unanswered; ``answered``
#: → some turn landed in its session (with or without an echoed token);
#: ``rebound`` → a later, DIFFERENT turn bound through the same token.
CLARIFY_TICKET_OPEN = "open"
CLARIFY_TICKET_ANSWERED = "answered"
CLARIFY_TICKET_REBOUND = "rebound"


class PersonaChatClarifyTicketStore:
    """Binds a clarify ANSWER to the thread its QUESTION was asked in.

    A child that calls ``clarify`` on the mission-chat lane has its question
    threaded back to the asker as ``clarify_request``. Until this store existed,
    the ONLY thing linking that question to its answer was the enclosing
    ``session_id``, and passing it back was enforced by prompt text alone — so a
    parent that omitted it fell through to ``policy_new_per_dispatch`` and the
    child read a bare choice with no question attached. Continuity that depends
    on a model reproducing an opaque identifier is not continuity; the runtime
    owns the binding now.

    A sidecar keyed store, deliberately NOT session meta:
    :meth:`PersonaChatMintReceiptStore.mint` writes meta WHOLESALE
    (``update_session_meta(root, json.dumps(meta))``), which is exactly why
    ``640131e8c`` had to add carry-forward logic for ``_dispatched_from``. A
    ticket parked in meta would be erased by the next mint against that root.

    **The filename is the digest of the token, never the token itself.** The
    token arrives as a caller-supplied string from a model; interpolating it
    into a path is traversal. Same precedent as the mint receipt store above.
    """

    def _root_dir(self) -> Path:
        return paths.store_root() / "persona_chat_clarify_tickets"

    def _path(self, token: str) -> Path:
        digest = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
        return self._root_dir() / f"{digest}.json"

    # ── Open-ticket index (by session) ──────────────────────────────────────
    #
    # WHY THIS EXISTS. ``open_ticket_for_session`` is the tokenless-settlement
    # lookup and it runs on nearly EVERY mission-chat turn. Reading it as a glob
    # over the ticket directory made each turn pay for every question ever asked
    # inside the live TTL window — a per-turn cost that grows with a store that
    # is supposed to be write-rare. The index answers the same question in a
    # bounded number of file reads: one index file, then the newest candidate
    # ticket it names.
    #
    # AUTHORITY AND SELF-HEALING. The index is a CACHE OF POINTERS, never a
    # second source of truth. Every token it hands back is re-read from its own
    # ticket file and re-verified (``state == open`` AND the record's own
    # ``chat_session_id`` matches) before it can bind anything, so a stale,
    # hand-edited, or half-written entry can only ever produce a MISS — never a
    # wrong binding. Entries that fail that verification are dropped on the way
    # past, so the index converges without a repair pass.
    #
    # THE MARKER FILE is what makes "no index file for this session" mean "no
    # open tickets" rather than "index lost". It is written LAST, after a full
    # rebuild from the ticket files themselves, so a crashed rebuild simply
    # leaves no marker and the next call redoes it (idempotent). Without it, a
    # session with no tickets — the overwhelmingly common case — could never be
    # told from a missing index and would fall back to the glob on every turn,
    # which is the cost this exists to retire.
    #
    # THAT CLAIM IS RETRACTABLE, and must be. Being a cache saves this index
    # from every failure that leaves it with an entry too MANY — the read path
    # verifies those away. Nothing saves it from an entry too FEW, because the
    # marker is precisely what stops anyone from going and looking. So the two
    # writes that can lose a pointer take the claim back rather than keep it:
    # a failed add (:meth:`_index_add`) and a rebuild racing a concurrent mint
    # (:meth:`_rebuild_index`, which unions instead of replacing). One extra
    # rebuild is the price; a permanently invisible open ticket is not.

    def _index_dir(self) -> Path:
        return self._root_dir() / "by_session"

    def _index_path(self, chat_session_id: str) -> Path:
        digest = hashlib.sha256(str(chat_session_id or "").encode("utf-8")).hexdigest()
        return self._index_dir() / f"{digest}.json"

    def _index_state_path(self) -> Path:
        # Leading underscore, never a sha256 hex digest, so it cannot collide
        # with a per-session file.
        return self._index_dir() / "_index_state.json"

    def _index_entries(self, chat_session_id: str) -> list[dict[str, Any]]:
        """The open-token pointers recorded for *chat_session_id*, newest first.

        "Could not read" collapses to "none recorded" here, which is the right
        answer for every caller that only READS the result — the lookup misses
        once and re-reads next turn, a cost it pays rather than a pointer it
        drops. It is the wrong answer for a caller about to write the list back,
        and that caller must use :meth:`_read_index` instead."""

        return self._read_index(chat_session_id) or []

    def _read_index(self, chat_session_id: str) -> list[dict[str, Any]] | None:
        """The recorded pointers, or ``None`` when the file could not be read.

        UNREADABLE IS NOT EMPTY, exactly as unreadable is not dead in
        :meth:`_sweep_index`. A file that is simply absent legitimately means
        "no pointers recorded" and answers ``[]``; a file that IS there but
        would not read has told us nothing, and answering ``[]`` for it hands a
        read-modify-write caller a blank slate to overwrite live pointers with.
        The failure is the ordinary Windows one the add path already documents
        for its WRITE — an AV or indexer holding the file for the instant we
        touch it — not corruption, and not crash-only."""

        try:
            text = self._index_path(chat_session_id).read_text(encoding="utf-8")
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
    def _index_payload(chat_session_id: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """The on-disk shape of one per-session index file. ONE writer of it.

        ``newest_created_at`` is the file's own record of the newest ticket it
        names, and it is what :meth:`_sweep_index` reclaims by. Recording it
        here rather than inferring it from the filesystem is the point: an
        mtime is a property of the FILE, which any backup, restore, sync, or
        copy tool is free to rewrite without touching a byte of content, while
        this is a property of the DATA and travels with it.

        Written by :meth:`_write_index` and :meth:`_rebuild_index` alike, so
        the two cannot disagree about the shape — the drift that made the
        rebuild's hand-built dict a second spelling of this one.
        """

        ordered = sorted(entries, key=lambda item: item["created_at"], reverse=True)
        return {
            # v2 adds ``newest_created_at``. Purely additive: a v1 file still
            # reads correctly (the field's absence is DERIVED from the entries,
            # see :meth:`_index_newest_created_at`), so there is no migration
            # pass and no rebuild owed.
            "schema_version": 2,
            "chat_session_id": str(chat_session_id),
            "newest_created_at": float(ordered[0]["created_at"]) if ordered else 0.0,
            "open_tokens": ordered,
        }

    def _write_index(self, chat_session_id: str, entries: list[dict[str, Any]]) -> bool:
        """Record *entries* as the open pointers for *chat_session_id*.

        Returns ``False`` when they could not be recorded at all. Whether that
        is survivable depends entirely on the direction: a failed DROP leaves a
        pointer the read path verifies away anyway, a failed ADD loses one
        outright — see :meth:`_index_add`."""

        path = self._index_path(chat_session_id)
        if not entries:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                return False
            return True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_json(path, self._index_payload(chat_session_id, entries))
        except OSError:
            return False
        return True

    def _index_newest_created_at(self, path: Path) -> float | None:
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

    def _rebuild_index(self) -> bool:
        """Rebuild every per-session index from the ticket files. Idempotent.

        Runs once per store (on the first mint or lookup after this code
        arrives, and again after any crash that left no marker). The marker is
        written LAST so a partial rebuild is simply redone rather than trusted.

        REFUSES TO CLAIM COMPLETENESS when any ticket file will not decode. The
        marker this method writes is not a cache entry, it is the sentence "the
        index may be trusted as complete" (:meth:`_ensure_index`), and it is
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

        records, unreadable = self.scan_records()
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
            self._index_dir().mkdir(parents=True, exist_ok=True)
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
                for entry in self._index_entries(root):
                    merged.setdefault(entry["clarify_token"], entry)
                _atomic_json(
                    self._index_path(root),
                    self._index_payload(root, list(merged.values())),
                )
            _atomic_json(
                self._index_state_path(), {"schema_version": 1, "rebuilt_at": time.time()}
            )
        except OSError:
            return False
        return True

    def _ensure_index(self) -> bool:
        """``True`` when the by-session index may be trusted as complete.

        ``False`` means the caller must fall back to the scan — correctness
        never depends on the index being present."""

        try:
            if self._index_state_path().exists():
                return True
        except OSError:
            return False
        return self._rebuild_index()

    def _invalidate_index(self) -> None:
        """Retract the completeness claim, forcing ONE rebuild on the next read.

        The marker is the whole reason "no index file for this session" may be
        read as "no open tickets". Anything that leaves that claim false has to
        take the claim back, or the index goes on answering a question it can no
        longer answer."""

        try:
            self._index_state_path().unlink(missing_ok=True)
        except OSError:  # pragma: no cover - defensive; the ticket is what matters
            pass

    def _index_add(self, chat_session_id: str, token: str, created_at: float) -> None:
        entries = self._read_index(chat_session_id)
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
            self._invalidate_index()
            return
        if any(entry["clarify_token"] == token for entry in entries):
            return
        entries.append({"clarify_token": token, "created_at": float(created_at)})
        entries.sort(key=lambda item: item["created_at"], reverse=True)
        if not self._write_index(chat_session_id, entries):
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
            self._invalidate_index()

    def _index_drop(self, chat_session_id: str, token: str) -> None:
        entries = self._index_entries(chat_session_id)
        remaining = [entry for entry in entries if entry["clarify_token"] != token]
        if len(remaining) != len(entries):
            # A failed drop is survivable and deliberately NOT invalidating: the
            # entry it left behind names a settled ticket, which the read path
            # re-verifies and discards. Only a lost ADD costs a ticket.
            self._write_index(chat_session_id, remaining)

    @staticmethod
    def new_token() -> str:
        import uuid

        return f"{CLARIFY_TOKEN_PREFIX}{uuid.uuid4().hex[:12]}"

    def mint(
        self,
        *,
        chat_session_id: str,
        persona_instance_id: str | None = None,
        persona_id: str | None = None,
        asked_by_client_message_id: str | None = None,
        asked_turn_id: str | None = None,
        requested_by_session: str | None = None,
    ) -> str | None:
        """Record a clarify ticket for the question this turn is asking.

        Returns the token to ship down inside ``clarify_request``, or ``None``
        when there is no session to bind to or the write failed. Best-effort by
        construction: a ticket that cannot be written must not fail the turn
        that produced a real reply — the caller degrades to today's precedence,
        which is exactly the pre-token behavior."""

        root = safe_assignment_text(chat_session_id, limit=240)
        if not root:
            return None
        token = self.new_token()
        record = {
            "schema_version": 1,
            "clarify_token": token,
            "chat_session_id": root,
            "persona_instance_id": safe_assignment_token(persona_instance_id) or None,
            "persona_id": safe_assignment_token(persona_id) or None,
            "asked_by_client_message_id": safe_assignment_text(
                asked_by_client_message_id, limit=240
            )
            or None,
            "asked_turn_id": safe_assignment_text(asked_turn_id, limit=240) or None,
            "requested_by_session": safe_assignment_text(requested_by_session, limit=240)
            or None,
            "state": CLARIFY_TICKET_OPEN,
            "created_at": time.time(),
            "answered_at": None,
            "answered_by_client_message_id": None,
            "bound_via": None,
        }
        path = self._path(token)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_json(path, record)
        except OSError:
            return None
        # GC RUNS HERE, on the mint, because this is the only cold seam in the
        # lane. The TTL was defined with no caller, so nothing ever pruned: the
        # directory grew for the life of the runtime, and since
        # ``open_ticket_for_session`` reads EVERY file in it, the tokenless
        # settlement on every mission-chat turn paid for every ticket ever
        # minted (measured: ~4s per turn at 400 tickets). A question is asked
        # far more rarely than a turn is taken, and this one already writes, so
        # it is the seam that can afford the scan the hot path cannot.
        #
        # After the write, never before: a sweep that ran first would still
        # leave this ticket unpruned, and one that ran on the read path would
        # put the cost back where it must not be. The just-written ticket is
        # never its own victim — ``created_at`` is now, and the cutoff is a full
        # TTL behind it. Best-effort: reclaiming disk must not fail the question
        # that was actually asked.
        try:
            self.sweep()
        except OSError:  # pragma: no cover - defensive; GC must never fail a turn
            pass
        # Index AFTER the ticket exists, so a crash between the two can only
        # lose the pointer (the tokenless settlement misses; the token itself
        # still binds), never publish a pointer to a ticket that is not there.
        # A rebuild triggered here already contains this ticket — the add is
        # idempotent, so the two cannot double-count.
        try:
            if self._ensure_index():
                self._index_add(root, token, float(record["created_at"]))
        except OSError:  # pragma: no cover - defensive; the ticket is what matters
            pass
        return token

    def resolve(self, token: str | None) -> dict[str, Any] | None:
        """The stored ticket for *token*, or ``None`` for unknown/unreadable.

        NEVER RAISES. An unknown or GC'd token must DEGRADE (the caller falls
        through to normal precedence and reports ``unknown_token``), never
        refuse: turning a pruned ticket into a hard failure would punish a
        parent that did exactly the right thing."""

        candidate = safe_assignment_text(token, limit=240)
        if not candidate:
            return None
        try:
            record = json.loads(self._path(candidate).read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(record, dict):
            return None
        # A record whose stored token does not match is not this token's ticket:
        # a digest collision or a hand-edited file must never bind a turn onto
        # somebody else's thread.
        if str(record.get("clarify_token") or "") != candidate:
            return None
        return record

    def settle(
        self,
        token: str | None,
        *,
        client_message_id: str | None = None,
        bound_via: str = "clarify_token",
    ) -> dict[str, Any] | None:
        """Mark the ticket answered, idempotently, and report its new state.

        Re-presentation with the SAME ``client_message_id`` (a lease re-entry, a
        relay retry) settles identically — the same replay-signal discipline the
        mint receipt uses. A settle from a DIFFERENT message is a genuine second
        answer and is recorded as ``rebound``: visible, never an error, because
        binding a token to its live thread is always the right outcome. The
        returned dict is the record as it now stands (or ``None`` when the token
        does not resolve)."""

        record = self.resolve(token)
        if record is None:
            return None
        message_id = safe_assignment_text(client_message_id, limit=240) or None
        already = record.get("answered_by_client_message_id")
        if record.get("state") == CLARIFY_TICKET_OPEN:
            record["state"] = CLARIFY_TICKET_ANSWERED
        elif already and message_id and already != message_id:
            record["state"] = CLARIFY_TICKET_REBOUND
        if not already or (message_id and already == message_id):
            record["answered_by_client_message_id"] = message_id or already
            record["answered_at"] = record.get("answered_at") or time.time()
            record["bound_via"] = record.get("bound_via") or str(bound_via)
        try:
            _atomic_json(self._path(str(record.get("clarify_token"))), record)
        except OSError:
            pass
        # A settled ticket is no longer a candidate for the tokenless lookup, so
        # it leaves the index. Best-effort: a failure here costs one wasted
        # verification on the next lookup, which then drops the entry itself.
        if record.get("state") != CLARIFY_TICKET_OPEN:
            try:
                self._index_drop(
                    str(record.get("chat_session_id") or ""),
                    str(record.get("clarify_token") or ""),
                )
            except OSError:  # pragma: no cover - defensive
                pass
        return record

    def open_ticket_for_session(self, chat_session_id: str | None) -> dict[str, Any] | None:
        """The newest OPEN ticket bound to *chat_session_id*, if any.

        Settlement without a token: any turn landing in a session with an open
        ticket settles it. Without this, every prompt-compliant-via-``session_id``
        parent would leave a permanently-open ticket and the adoption metric
        would lie in the pessimistic direction.

        THIS RUNS ON NEARLY EVERY MISSION-CHAT TURN, so it answers from the
        by-session index — one index read plus the newest ticket it names — and
        falls back to the full scan only when the index cannot be established.
        The index is never trusted on its own: every token it offers is re-read
        and re-verified against its own record, so the worst a stale entry can
        do is cost one wasted read and get itself dropped."""

        root = safe_assignment_text(chat_session_id, limit=240)
        if not root:
            return None
        if not self._ensure_index():
            return self._scan_open_ticket_for_session(root)
        entries = self._index_entries(root)
        stale = 0
        for entry in entries:
            record = self.resolve(entry["clarify_token"])
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
                self._write_index(root, entries[stale:])
            return record
        if stale:
            self._write_index(root, [])
        return None

    def _scan_open_ticket_for_session(self, root: str) -> dict[str, Any] | None:
        """Index-free lookup: the pre-index behavior, kept as the fallback.

        Reached only when the index could not be written (read-only or full
        store root). Correctness must never depend on the index existing."""

        newest: dict[str, Any] | None = None
        for record in self._iter_records():
            if record.get("state") != CLARIFY_TICKET_OPEN:
                continue
            if str(record.get("chat_session_id") or "") != root:
                continue
            if newest is None or float(record.get("created_at") or 0.0) > float(
                newest.get("created_at") or 0.0
            ):
                newest = record
        return newest

    def scan_tickets(self) -> tuple[list[dict[str, Any]], int]:
        """:meth:`list_tickets`, plus how many ticket files would not decode.

        The count travels because this readout's whole point is a RATIO. The
        adoption metric is computed over the entire store — the site that builds
        it says so, and says why: "an adoption ratio that moved because the
        operator asked to see fewer rows would be a lying metric". A file that
        silently drops out of the scan moves the denominator in exactly the way
        that comment forbids, and does it without the operator having asked for
        anything. So the readout states it instead of absorbing it.
        """

        records, unreadable = self.scan_records()
        records.sort(key=lambda record: float(record.get("created_at") or 0.0), reverse=True)
        return records, unreadable

    def sweep(self, *, ttl_seconds: float = CLARIFY_TICKET_TTL_SECONDS) -> int:
        """Prune ticket files older than *ttl_seconds*. Returns the count.

        TTL governs GC only — nothing consults it when deciding whether a token
        binds, so a ticket that survives past its TTL keeps working right up
        until a sweep removes the file. One rule, no cliff."""

        cutoff = time.time() - max(float(ttl_seconds), 0.0)
        pruned = 0
        for record in self._iter_records():
            if not self._expired(float(record.get("created_at") or 0.0), cutoff):
                continue
            try:
                self._path(str(record.get("clarify_token"))).unlink(missing_ok=True)
            except OSError:
                continue
            pruned += 1
        self._sweep_index(cutoff)
        return pruned

    @staticmethod
    def _expired(created_at: float, cutoff: float) -> bool:
        """THE expiry predicate, and there is deliberately only one.

        The ticket loop and the index sweep must agree EXACTLY about what
        "past its TTL" means, because the index sweep's entire safety argument
        is "every ticket this file names was already unlinked by the ticket
        loop". Two spellings of the comparison — or a second cutoff constant —
        make that argument true only by coincidence, and the day it stops being
        true the index file naming a LIVE ticket is the one deleted."""

        return created_at <= cutoff

    def _sweep_index(self, cutoff: float) -> None:
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
            entries = list(self._index_dir().glob("*.json"))
        except OSError:
            return
        state_path = self._index_state_path()
        for entry in entries:
            if entry == state_path:
                continue
            newest = self._index_newest_created_at(entry)
            # UNREADABLE IS NOT DEAD. A file we could not read has not been
            # proven to name only expired tickets, and the sweep only ever
            # deletes on proof: keeping an inert file costs one small file,
            # deleting a live one costs a ticket nothing will look for again.
            if newest is None or not self._expired(newest, cutoff):
                continue
            try:
                entry.unlink(missing_ok=True)
            except OSError:
                continue

    def scan_records(self) -> tuple[list[dict[str, Any]], int]:
        """Every ticket record on disk, beside how many files did not decode.

        THE chokepoint. :meth:`_iter_records` is the thin view over it, so the
        callers that only want records keep their shape while the two that must
        not describe a short answer as complete can ask the fuller question:
        :meth:`_rebuild_index`, which mints a COMPLETENESS CLAIM from this scan,
        and the operator readout, whose adoption ratio is computed over the whole
        store.

        This is the same law :meth:`_read_index` already states for the index
        file — UNREADABLE IS NOT EMPTY — applied to the ticket files themselves.
        The failure it counts is usually the ordinary Windows one that method
        documents: an AV or indexer holding a file for the instant we touch it,
        which is transient, so the file it hid is very likely readable a second
        later. That is precisely why it must not be silently absorbed into a
        permanent claim.
        """

        root = self._root_dir()
        try:
            entries = sorted(root.glob("*.json"))
        except OSError:
            return [], 0
        records: list[dict[str, Any]] = []
        unreadable = 0
        for entry in entries:
            try:
                record = json.loads(entry.read_text(encoding="utf-8"))
            except Exception:
                unreadable += 1
                continue
            if isinstance(record, dict) and record.get("clarify_token"):
                records.append(record)
        return records, unreadable

    def _iter_records(self) -> Iterator[dict[str, Any]]:
        yield from self.scan_records()[0]
