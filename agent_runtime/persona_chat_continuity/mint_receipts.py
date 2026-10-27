"""The ONE idempotent chat-root mint, and the dispatch lineage it records.

:func:`mint_chat_root` is the only way a persona chat root is minted: the send
lane (a fresh dispatch thread, the operator console's first message) and
``persona instance open-chat --new-session`` both call it, over ONE receipt
store — ``agent_runtime.persona_chat_mints`` (``reserve_persona_chat_mint``).
It used to be two: this module kept a second receipt format keyed on
``(instance, key)`` with its own phase order, so a reader had to trace both to
know what a replay answers (RT-CHAT-MINT-TWO-RECEIPT-STORES).

One :class:`Mint` runs its phases in the order the contract names:
precondition -> reserve -> (replay of a bound receipt: observe and return) ->
early bind (``select`` only) -> session -> meta -> title -> mark bound, with
:meth:`Mint.retract` the ONE place a failed write undoes the bind it was
ordered behind.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import paths
from ..conversation_owner import ConversationOwnerError, require_session_owner
from ..dispatch_session_policy import superseded_session_id
from ..persona_assignments import PersonaInstanceStore, persona_chat_session_id_for
from ..persona_chat_mints import PersonaChatMintTransaction, reserve_persona_chat_mint
from ..serde import safe_assignment_text, safe_assignment_token

__layer__ = "stores"


PERSONA_CHAT_SESSION_SOURCE = "agent_runtime_persona_chat"


@dataclass(frozen=True)
class MintedChatRoot:
    """What one :func:`mint_chat_root` call answers — first mint and replay alike."""

    session_id: str
    persona_instance_id: str
    state: str
    idempotent_replay: bool
    select_session: bool
    client_scope: str | None
    instance: Any
    #: The lineage this mint actually RECORDED (not the lineage it was asked
    #: for), so a reply envelope reports the same predecessor the session meta
    #: holds — on a first mint and on a replay alike.
    dispatched_from: dict[str, str] = field(default_factory=dict)

    @property
    def default_chat_session_id(self) -> str | None:
        return getattr(self.instance, "default_chat_session_id", None)

    @property
    def selected(self) -> bool:
        return getattr(self.instance, "session_id", None) == self.session_id


def mint_chat_root(
    *,
    instance_store: PersonaInstanceStore,
    session_db: Any,
    persona_id: str,
    persona_instance_id: str,
    idempotency_key: str,
    title: str | None = None,
    select: bool = True,
    dispatched_from: dict[str, Any] | None = None,
    client_scope: str | None = None,
) -> MintedChatRoot:
    """Reserve-then-create one persona instance chat root, idempotently.

    ``select`` binds the root as the instance's selected chat; ``False`` makes
    an independent conversation the instance does not point at. A replay of a
    key whose receipt is ``bound`` is OBSERVATIONAL — it answers the original
    root and never moves the instance pointer back over a chat selected since.
    A ``reserved`` receipt (a mint that died part-way) resumes on the SAME root.

    ``dispatched_from`` records task-scoped dispatch lineage — the thread this
    fresh session superseded, and the sender session that asked for it — into
    the session meta as ``_dispatched_from``. It is honoured by the pass that
    CREATES the thread; a resumed or replayed mint carries the stored block
    forward unchanged. It rides the SAME meta write as ``mission_chat_root_id``
    and deliberately does NOT touch ``parent_session_id``: on the persona-chat
    lane that column is claimed by native-compression lineage. Marker-key
    precedent: ``_delegate_from`` / ``_branched_from``.

    Order of operations is load-bearing: assert bindable -> reserve the receipt
    -> BIND -> create the session -> meta -> title. Binding before the first
    session-visible write is what keeps a ``retire`` landing mid-lane from
    leaving a titled thread for a placement that no longer exists (see
    :meth:`Mint.early_bind`); the bind is RETRACTED when the row cannot be
    written, and the failure surfaces as ``PersonaChatPersistenceError``. The
    receipt stays ``reserved`` through that failure on purpose: a same-key
    retry resolves the SAME root and completes.

    Raises ``PersonaChatMintError`` (bad key, scope conflict, lock busy),
    ``RetiredPersonaInstanceError``, ``PersonaChatPersistenceError`` and, on a
    replay whose root is gone or owned by another client,
    ``ConversationOwnerError``. A refusal raised after the receipt was reserved
    carries it as ``exc.mint_receipt`` so a caller can name the root a retry
    will resolve.
    """

    return Mint(
        instance_store=instance_store,
        session_db=session_db,
        persona_id=persona_id,
        persona_instance_id=persona_instance_id,
        idempotency_key=idempotency_key,
        title=title,
        select=select,
        dispatched_from=dispatched_from,
        client_scope=client_scope,
    ).run()


def legacy_mint_receipt_path(persona_instance_id: str, idempotency_key: str) -> Path:
    """Where the retired second receipt store kept a send-lane receipt.

    Read once, as a SEED: a send that reserved a root under the old store and
    is retried after the upgrade resumes that root instead of minting a second
    thread. Nothing writes this path any more.
    """

    digest = hashlib.sha256(f"{persona_instance_id}\0{idempotency_key}".encode()).hexdigest()
    return paths.persona_chat_mint_receipts_dir() / f"{digest}.json"


def _legacy_root(persona_instance_id: str, idempotency_key: str) -> str:
    try:
        raw = json.loads(
            legacy_mint_receipt_path(persona_instance_id, idempotency_key).read_text(encoding="utf-8")
        )
    except Exception:
        return ""
    if not isinstance(raw, dict):
        return ""
    return safe_assignment_text(raw.get("root_chat_session_id"), limit=240)


class Mint:
    """One idempotent mint, as its phases. Fields are the state the phases share."""

    def __init__(
        self,
        *,
        instance_store: PersonaInstanceStore,
        session_db: Any,
        persona_id: str,
        persona_instance_id: str,
        idempotency_key: str,
        title: str | None,
        select: bool,
        dispatched_from: dict[str, Any] | None,
        client_scope: str | None,
    ) -> None:
        self.instance_store = instance_store
        self.session_db = session_db
        self.persona_id = persona_id
        self.instance_id = safe_assignment_token(persona_instance_id)
        self.key = idempotency_key
        self.title = title
        self.select = bool(select)
        self.dispatched_from = dispatched_from
        self.client_scope = client_scope
        self.bind_target_id = ""
        self.transaction: PersonaChatMintTransaction | None = None
        self.root = ""
        self.replayed = False
        self.bound_early = False
        self.previous_row: Any = None
        self.instance: Any = None

    def run(self) -> MintedChatRoot:
        self.precondition()
        with reserve_persona_chat_mint(
            idempotency_key=self.key,
            persona_id=self.persona_id,
            persona_instance_id=self.instance_id,
            session_id=self.seed_root(),
            client_scope=self.client_scope,
            select_session=self.select,
        ) as transaction:
            self.transaction = transaction
            self.root = transaction.receipt.session_id
            self.replayed = transaction.receipt.idempotent_replay
            try:
                if transaction.receipt.bound:
                    return self.observe_replay()
                self.early_bind()
                self.create_session()
                lineage = self.write_meta()
                self.write_title()
                return self.commit(lineage)
            except Exception as exc:
                exc.mint_receipt = transaction.receipt  # type: ignore[attr-defined]
                raise

    def precondition(self) -> None:
        if not self.instance_id:
            raise ValueError("persona_instance_id is required")
        # PRECONDITION, asserted before this lane's FIRST durable write (the
        # receipt), through the SAME seam the bind itself uses
        # (``assert_bindable`` -> one derivation of the target id, one
        # retirement rule, one refusal). It closes the refusal that is TRUE AT
        # ENTRY — every dispatch at a deleted placement. The narrower race (a
        # ``retire`` landing WHILE this lane runs) is closed by the early bind.
        #
        # ``instance_id`` deliberately stays the CALLER's token: it keys the
        # receipt and derives the root session id. The id the seam RESOLVES is
        # kept for the retraction, which must name the row ``open_chat`` wrote.
        self.bind_target_id = self.instance_store.assert_bindable(
            persona_id=self.persona_id, persona_instance_id=self.instance_id
        )

    def seed_root(self) -> str:
        """The root a FIRST reservation records: a legacy receipt's, else a fresh id."""

        key = safe_assignment_text(self.key, limit=240)
        return (key and _legacy_root(self.instance_id, key)) or persona_chat_session_id_for(
            self.instance_id
        )

    def observe_replay(self) -> MintedChatRoot:
        """A BOUND receipt: answer the original root, move nothing.

        A retry after a confirmed response loss must be observational — the
        instance may have selected a newer chat since this mint completed.
        """

        persisted = self.session_db.get_session(self.root)
        if persisted is None:
            raise ConversationOwnerError("session_not_found")
        require_session_owner(persisted, self.client_scope)
        self.instance = self.instance_store.get(self.bind_target_id)
        return self.result(_stored_dispatch_lineage(self.session_db, self.root))

    def early_bind(self) -> None:
        """EARLY BIND, after the receipt and before the first session-visible write.

        The bind is the step that proves the target is still live, so it runs
        before the first SESSION-visible write: a ``retire`` that lands after
        this point archives a row that legitimately owned the thread (its
        tombstone carries the pointer — preserved history is what ``retire``
        promises), and one that lands before it is refused here with nothing
        written but the internal receipt.

        The price is a WINDOW: until the session row is written the instance
        points at a root no transcript store holds — the phantom
        ``agent_runtime.persona_chat_durability`` exists to prevent, and a
        permanent one (``resolve_default_chat_session_id_for_instance``
        re-offers the pointer forever). This lane's ``session_db`` is the
        CALLER's handle, so it cannot persist through the process-default
        store; the window is closed from the other end instead — :meth:`retract`
        undoes the bind when the write it was ordered ahead of cannot be made.

        An unselected mint (``select=False``) binds nothing: the instance's
        pointer is not this root's, so there is no window to close.
        """

        if not self.select:
            return
        try:
            self.previous_row = self.instance_store.get(self.bind_target_id)
        except Exception:
            self.previous_row = None
        self.instance = self.instance_store.open_chat(
            persona_id=self.persona_id,
            persona_instance_id=self.instance_id,
            session_id=self.root,
        )
        self.bound_early = True

    def create_session(self) -> None:
        # Lazy import — ``persona_chat_durability`` imports THIS package, so a
        # module-level import would close the cycle.
        from ..persona_chat_durability import ensure_persona_chat_session

        try:
            ensure_persona_chat_session(
                session_db=self.session_db,
                session_id=self.root,
                persona_id=self.persona_id,
                required=True,
                client_scope=self.client_scope,
                independent=not self.select,
            )
        except Exception:
            self.retract()
            raise

    def retract(self) -> None:
        """Undo the early bind: the ONE place a failed write takes the pointer back."""

        if not self.bound_early:
            return
        self.instance_store.rollback_chat_root_bind(
            persona_instance_id=self.bind_target_id,
            root_session_id=self.root,
            previous=self.previous_row,
        )

    def write_meta(self) -> dict[str, str]:
        from ..persona_chat_durability import persona_chat_ownership

        meta = {
            **persona_chat_ownership(
                self.root,
                self.persona_id,
                client_scope=self.client_scope,
                independent=not self.select,
            ),
            "mission_chat_root_id": self.root,
            "persona_instance_id": self.instance_id,
        }
        if self.replayed:
            # A RESUMED mint (reserved receipt): lineage is established ONCE, by
            # the pass that created the thread, and never recomputed — the
            # caller's ``predecessor`` was read from the default-thread pointer
            # this very session has since BECOME (a self-reference, or after an
            # interleaved dispatch a LATER thread: an inverted arrow), and
            # ``requested_by_session`` belongs to whoever asked for the ORIGINAL
            # mint. This write replaces the meta wholesale, so carry the stored
            # block forward; an empty one means the thread was born without
            # lineage — silence, never a fabricated arrow.
            lineage = _stored_dispatch_lineage(self.session_db, self.root)
        else:
            lineage = _dispatch_lineage_meta(self.dispatched_from, root=self.root)
        if lineage:
            meta["_dispatched_from"] = lineage
        self.session_db.update_session_meta(self.root, json.dumps(meta, sort_keys=True))
        return lineage

    def write_title(self) -> None:
        title = safe_assignment_text(self.title, limit=120)
        if not title or self.session_db.get_session_title(self.root):
            return
        try:
            self.session_db.set_session_title(self.root, title)
        except Exception as exc:
            if "already in use" not in str(exc).lower():
                raise
            self.session_db.set_session_title(self.root, f"{title} · {self.root[-8:]}")

    def commit(self, lineage: dict[str, str]) -> MintedChatRoot:
        assert self.transaction is not None
        self.transaction.mark_bound()
        if self.instance is None:
            self.instance = self.instance_store.get(self.bind_target_id)
        return self.result(lineage)

    def result(self, lineage: dict[str, str]) -> MintedChatRoot:
        assert self.transaction is not None
        receipt = self.transaction.receipt
        return MintedChatRoot(
            session_id=self.root,
            persona_instance_id=self.bind_target_id,
            state=receipt.state,
            idempotent_replay=receipt.idempotent_replay,
            select_session=receipt.select_session,
            client_scope=receipt.client_scope,
            instance=self.instance,
            dispatched_from=dict(lineage),
        )


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
    """Atomic JSON write for this package's own small receipts (clarify tickets)."""

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(str(tmp), str(path))
