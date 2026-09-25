"""The idempotent chat-root mint and the dispatch lineage it records.

``PersonaChatMintReceiptStore.mint`` is one :class:`Mint`, run as its phases in
the order the mint's contract names: precondition -> receipt -> early bind ->
session -> meta -> title -> commit, with :meth:`Mint.retract` the ONE place a
failed write undoes the bind it was ordered behind.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .. import paths
from ..dispatch_session_policy import superseded_session_id
from ..file_locks import try_lock_fd, unlock_fd
from ..persona_assignments import PersonaInstanceStore, persona_chat_session_id_for
from ..serde import safe_assignment_text, safe_assignment_token

__layer__ = "stores"


PERSONA_CHAT_SESSION_SOURCE = "agent_runtime_persona_chat"


class PersonaChatMintReceiptStore:
    def _path(self, instance_id: str, key: str) -> Path:
        digest = hashlib.sha256(f"{instance_id}\0{key}".encode("utf-8")).hexdigest()
        return paths.store_root() / "persona_chat_mint_receipts" / f"{digest}.json"

    def mint(
        self,
        *,
        instance_store: PersonaInstanceStore,
        session_db: Any,
        persona_id: str,
        persona_instance_id: str,
        idempotency_key: str,
        title: str | None = None,
        dispatched_from: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reserve-then-create the instance's canonical chat root.

        ``dispatched_from`` records task-scoped dispatch lineage — the thread
        this fresh session superseded, and the sender session that asked for it
        — into the session meta as ``_dispatched_from``. It is honoured by the
        mint that CREATES the thread; a replay of the same idempotency key
        ignores it and carries the stored block forward unchanged. It rides the
        SAME meta write as ``mission_chat_root_id`` (one write, one authority)
        rather than a second update, and deliberately does NOT touch
        ``parent_session_id``:
        on the persona-chat lane that column is claimed by native-compression
        lineage (``native_lineage_summary`` raises on a foreign parent, and
        usage aggregation blanks), so borrowing it for relay provenance would
        corrupt both. Marker-key precedent: ``_delegate_from`` / ``_branched_from``.

        Order of operations is load-bearing, not incidental: assert bindable →
        reserve the receipt → BIND → create the session → meta → title. The bind
        used to be last, which is why a ``retire`` landing mid-lane still left a
        titled thread behind for a placement that no longer existed. See
        :meth:`Mint.early_bind`.

        That ordering's own cost — a bound pointer standing for the instant
        before its transcript row exists — is paid by RETRACTING the bind when
        the row cannot be written (``rollback_chat_root_bind``), and the failure
        then surfaces as :class:`PersonaChatPersistenceError` rather than as a
        raw storage exception. The receipt stays ``reserved`` through that
        failure on purpose: a same-key retry resolves the SAME root and
        completes, so a crash in the same window (which no in-process rollback
        can cover) is repaired rather than duplicated.
        """

        return Mint(
            self,
            instance_store=instance_store,
            session_db=session_db,
            persona_id=persona_id,
            persona_instance_id=persona_instance_id,
            idempotency_key=idempotency_key,
            title=title,
            dispatched_from=dispatched_from,
        ).run()


class Mint:
    """One idempotent mint, as its phases. Fields are the state the phases share."""

    def __init__(
        self,
        store: PersonaChatMintReceiptStore,
        *,
        instance_store: PersonaInstanceStore,
        session_db: Any,
        persona_id: str,
        persona_instance_id: str,
        idempotency_key: str,
        title: str | None,
        dispatched_from: dict[str, Any] | None,
    ) -> None:
        self.store = store
        self.instance_store = instance_store
        self.session_db = session_db
        self.persona_id = persona_id
        self.instance_id = safe_assignment_token(persona_instance_id)
        self.key = safe_assignment_text(idempotency_key, limit=240)
        self.title = title
        self.dispatched_from = dispatched_from
        self.bind_target_id = ""
        self.path = Path()
        self.receipt: dict[str, Any] = {}
        self.root = ""
        self.replayed = False
        self.previous_row: Any = None
        self.instance: Any = None

    def run(self) -> dict[str, Any]:
        self.precondition()
        fd = self.lock_receipt()
        try:
            self.reserve_receipt()
            self.early_bind()
            self.create_session()
            lineage = self.write_meta()
            self.write_title()
            return self.commit(lineage)
        finally:
            try:
                unlock_fd(fd)
            except OSError:
                pass
            os.close(fd)

    def precondition(self) -> None:
        if not self.instance_id or not self.key:
            raise ValueError("persona_instance_id and idempotency_key are required")
        # PRECONDITION, asserted before this lane's FIRST durable write, through
        # the SAME seam the bind itself uses (``assert_bindable`` → one
        # derivation of the target id, one retirement rule, one refusal). It
        # reports the id the seam resolved, not the caller's raw token: a refusal
        # reachable from three sites must not identify its target three ways.
        #
        # It closes the refusal that is TRUE AT ENTRY — the target was already
        # retired when the mint arrived, which is every dispatch at a deleted
        # placement. The narrower race (a ``retire`` landing WHILE this lane
        # runs) is closed by the early bind, not here.
        #
        # ``instance_id`` deliberately stays the CALLER's token: it keys the
        # idempotency receipt path and derives the root session id, and
        # canonicalizing it here would re-key every in-flight receipt — a replay
        # would miss its own reservation and mint a SECOND thread for a task
        # that already has one.
        #
        # The id it RESOLVES is kept: the retraction has to name the row
        # ``open_chat`` will write, and re-deriving it there would be the second
        # derivation this seam exists to prevent.
        self.bind_target_id = self.instance_store.assert_bindable(
            persona_id=self.persona_id, persona_instance_id=self.instance_id
        )
        self.path = self.store._path(self.instance_id, self.key)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def lock_receipt(self) -> int:
        """The receipt's own byte lock, held (blocking) for the whole mint."""

        fd = os.open(str(self.path.with_suffix(".lock")), os.O_CREAT | os.O_RDWR)
        while True:
            try:
                try_lock_fd(fd)
                return fd
            except OSError:
                time.sleep(0.01)

    def reserve_receipt(self) -> None:
        try:
            self.receipt = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.receipt = {}
        self.root = safe_assignment_text(self.receipt.get("root_chat_session_id"), limit=240)
        # THE replay signal: a receipt that already names a root is one this
        # key established on an earlier pass. Anything a retry must NOT
        # re-derive branches on this fact, never on the shape of the values
        # the retry happened to compute.
        self.replayed = bool(self.root)
        if self.replayed:
            return
        self.root = persona_chat_session_id_for(self.instance_id)
        self.receipt = {
            "schema_version": 1,
            "persona_instance_id": self.instance_id,
            "idempotency_key": self.key,
            "root_chat_session_id": self.root,
            "state": "reserved",
            "created_at": time.time(),
        }
        _atomic_json(self.path, self.receipt)

    def early_bind(self) -> None:
        """EARLY BIND, after the receipt and before the first session-visible write.

        This used to be the LAST step of the lane, and that position was the
        whole remaining defect: ``retire`` refuses only on a live run/worker
        binding or an active assignment, and a chat mint held neither until it
        bound — so a ``retire`` landing after the precondition still let the
        lane create the session, write its meta and TITLE it before the bind
        refused, leaving a titled thread in Mission Control for a placement that
        no longer exists.

        Binding first inverts that. The bind is the step that proves the target
        is still live, so it runs before the first SESSION-visible write; from
        here on every write belongs to a target this lane has already proven
        bindable. A ``retire`` that lands after this point archives a row that
        legitimately owned the thread — its tombstone carries the pointer, and
        preserved chat history is exactly what ``retire`` promises. No orphan
        either way.

        Ordered AFTER the receipt reservation on purpose: the receipt is what
        makes the whole lane idempotent, it is internal (never a Mission Control
        row), and reserving first means a crash between the two is repaired by a
        retry that resolves the same root instead of minting a second one.

        …and the price of binding first is a WINDOW: from here until the session
        row is written, the instance points at a root no transcript store holds.
        That is the phantom ``agent_runtime.persona_chat_durability`` was written
        to make impossible on the create lane, and it is permanent —
        ``resolve_default_chat_session_id_for_instance`` re-offers a chat-shaped
        own-instance pointer forever without ever asking whether it resolves, so
        every later ``mission-chat message`` is refused ``unknown_chat_session``.

        The create lane closed it by persisting AT the bind argument. This lane
        cannot: the ordering above is load-bearing, and its ``session_db`` is the
        CALLER's handle (dispatch, relay and argv each pass their own), so
        routing through ``ensure_durable_persona_chat_root`` — which acquires the
        process DEFAULT store — would write the row into a different database
        from the one this mint's own reader dereferences. The window is closed
        from the other end instead: :meth:`retract` undoes the bind when the
        write it was ordered ahead of cannot be made.

        ``previous_row`` is the row as it stood BEFORE the bind, ``None`` when
        the bind is what creates it; the retraction restores exactly that, and
        only while the live pointer still names OUR root.
        """

        try:
            self.previous_row = self.instance_store.get(self.bind_target_id)
        except Exception:
            self.previous_row = None
        self.instance = self.instance_store.open_chat(
            persona_id=self.persona_id,
            persona_instance_id=self.instance_id,
            session_id=self.root,
        )

    def create_session(self) -> None:
        try:
            self.session_db.create_session(
                session_id=self.root,
                source=PERSONA_CHAT_SESSION_SOURCE,
                model=None,
                system_prompt=f"Mission Control persona chat for {self.persona_id}",
            )
        except Exception as exc:
            self.retract()
            # Typed, and chained: this lane is reached over RPC and from argv,
            # and a bare storage exception escaping it reaches the operator as a
            # traceback instead of the persistence frame the chat lanes already
            # speak. Lazy import — ``persona_chat_durability`` imports THIS
            # package, so a module-level import would close the cycle.
            from ..persona_chat_durability import persona_chat_persistence_failed

            persona_chat_persistence_failed("session_create", exc, required=True)
            raise  # pragma: no cover — the helper always raises when required

    def retract(self) -> None:
        """Undo the early bind: the ONE place a failed write takes the pointer back."""

        self.instance_store.rollback_chat_root_bind(
            persona_instance_id=self.bind_target_id,
            root_session_id=self.root,
            previous=self.previous_row,
        )

    def write_meta(self) -> dict[str, str]:
        meta = {
            "mission_chat_root_id": self.root,
            "persona_instance_id": self.instance_id,
            "source": PERSONA_CHAT_SESSION_SOURCE,
        }
        if self.replayed:
            # REPLAY: lineage is established ONCE, by the mint that created the
            # thread, and is never recomputed. A retry cannot re-derive it,
            # because both inputs have gone stale in ways that lie:
            #   * the caller's `predecessor` was read from the instance's
            #     default-thread pointer, which this very session has since
            #     BECOME — so on a same-key retry it is a self-reference
            #     (dropped), and after an INTERLEAVED later dispatch it is that
            #     later thread, which this session never superseded. Recording
            #     it would invert the arrow (A claiming it retired B when A came
            #     first).
            #   * `requested_by_session` belongs to whoever asked for the
            #     ORIGINAL mint; the retry's sender is not that fact.
            # And this meta write replaces the stored value wholesale, so
            # anything not carried forward is ERASED. Carry it forward
            # unconditionally: the stored block is the whole truth, and an empty
            # one means the thread was born without lineage. (A mint that died
            # between reserving the receipt and writing this meta therefore
            # keeps no lineage — silence, never a fabricated arrow.)
            lineage = _stored_dispatch_lineage(self.session_db, self.root)
        else:
            lineage = _dispatch_lineage_meta(self.dispatched_from, root=self.root)
        if lineage:
            meta["_dispatched_from"] = lineage
        self.session_db.update_session_meta(self.root, json.dumps(meta, sort_keys=True))
        return lineage

    def write_title(self) -> None:
        if not self.title or self.session_db.get_session_title(self.root):
            return
        try:
            self.session_db.set_session_title(self.root, self.title)
        except Exception as exc:
            if "already in use" not in str(exc).lower():
                raise
            self.session_db.set_session_title(self.root, f"{self.title} · {self.root[-8:]}")

    def commit(self, lineage: dict[str, str]) -> dict[str, Any]:
        self.receipt.update({"state": "completed", "completed_at": time.time()})
        _atomic_json(self.path, self.receipt)
        return {
            **self.receipt,
            "default_chat_session_id": self.instance.default_chat_session_id,
            # The lineage this mint actually RECORDED (not the lineage it was
            # asked for), so the reply envelope reports the same predecessor the
            # session meta holds — on a first mint and on a replay alike. Not
            # persisted into the receipt file: the meta is its home.
            "dispatched_from": dict(lineage),
        }


#: Keys accepted inside ``_dispatched_from``. An allow-list rather than a
#: pass-through: session meta is read back by projections and shipped to the
#: launcher, so an unbounded caller-supplied dict is a payload-growth and
#: leak surface, not provenance.
_DISPATCH_LINEAGE_KEYS = ("predecessor_chat_session_id", "requested_by_session")


def _stored_dispatch_lineage(session_db: Any, root: str) -> dict[str, str]:
    """The ``_dispatched_from`` already recorded for *root*, if any."""

    try:
        row = session_db.get_session(root)
    except Exception:
        return {}
    raw = (row if isinstance(row, dict) else {}).get("model_config")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except Exception:
            return {}
    stored = raw.get("_dispatched_from") if isinstance(raw, dict) else None
    if not isinstance(stored, dict):
        return {}
    return {
        str(key): text
        for key in _DISPATCH_LINEAGE_KEYS
        if (text := safe_assignment_text(stored.get(key), limit=240))
    }


def _dispatch_lineage_meta(
    dispatched_from: dict[str, Any] | None, *, root: str
) -> dict[str, str]:
    """Bounded, string-only projection of the dispatch lineage.

    FRESH MINTS ONLY — a replay carries the stored block forward instead of
    re-projecting caller arguments that have gone stale (see :meth:`mint`).
    *root* is the session this meta belongs to; a predecessor equal to it is
    dropped through the shared :func:`superseded_session_id` rule, which a
    fresh mint's brand-new id cannot trip but which keeps the one lineage
    projection honest for any caller that hands in the thread itself."""

    if not isinstance(dispatched_from, dict):
        return {}
    lineage: dict[str, str] = {}
    for key in _DISPATCH_LINEAGE_KEYS:
        value = safe_assignment_text(dispatched_from.get(key), limit=240)
        if key == "predecessor_chat_session_id":
            value = superseded_session_id(value, established=root) or ""
        if value:
            lineage[key] = value
    return lineage


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(str(tmp), str(path))
