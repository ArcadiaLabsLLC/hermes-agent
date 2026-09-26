"""Clarify tickets: bind a clarify ANSWER to the thread its QUESTION was asked in."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterator

from .. import paths
from ..serde import safe_assignment_text, safe_assignment_token

from .clarify_index import CLARIFY_TICKET_OPEN, ClarifyTicketIndex, expired
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
#: ``CLARIFY_TICKET_OPEN`` is spelled once, in :mod:`.clarify_index` (the index
#: points only at open tickets, and imports nothing from this module).
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

    def __init__(self) -> None:
        #: The by-session open-ticket index (:mod:`.clarify_index`): a cache of
        #: pointers the ticket files back, built and swept through this store.
        self.index = ClarifyTicketIndex(self._root_dir, self.scan_records)

    def _root_dir(self) -> Path:
        return paths.store_root() / "persona_chat_clarify_tickets"

    def _path(self, token: str) -> Path:
        digest = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
        return self._root_dir() / f"{digest}.json"

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
            if self.index.ensure():
                self.index.add(root, token, float(record["created_at"]))
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
                self.index.drop(
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
        falls back to the full scan only when the index cannot be established."""

        root = safe_assignment_text(chat_session_id, limit=240)
        if not root:
            return None
        if not self.index.ensure():
            return self._scan_open_ticket_for_session(root)
        return self.index.lookup(root, self.resolve)

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
            if not expired(float(record.get("created_at") or 0.0), cutoff):
                continue
            try:
                self._path(str(record.get("clarify_token"))).unlink(missing_ok=True)
            except OSError:
                continue
            pruned += 1
        self.index.sweep(cutoff)
        return pruned

    def scan_records(self) -> tuple[list[dict[str, Any]], int]:
        """Every ticket record on disk, beside how many files did not decode.

        THE chokepoint. :meth:`_iter_records` is the thin view over it, so the
        callers that only want records keep their shape while the two that must
        not describe a short answer as complete can ask the fuller question:
        ``ClarifyTicketIndex.rebuild``, which mints a COMPLETENESS CLAIM from this scan,
        and the operator readout, whose adoption ratio is computed over the whole
        store.

        This is the same law ``ClarifyTicketIndex.read`` already states for the index
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
