"""The write-path fences: the tombstone (archived-actor) fence and the
class-key fences for a local write and for an adoption.

Functions over an ``OfficeStore`` (composition — the class binds each one as a
method, so ``store.<name>(...)`` reads exactly as before).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_runtime.errors import ActorArchived
from agent_runtime.models import OfficeActor
from agent_runtime.office_store.normalize import _normalize_actor_persona_ref

if TYPE_CHECKING:
    from agent_runtime.office_store.store import OfficeStore

__layer__ = "stores"

__all__ = [
    "_guard_archived_actor",
    "_guard_class_keyed_adoption",
    "_guard_class_keyed_write",
]


def _guard_archived_actor(
    store: OfficeStore,
    workspace_id: str,
    *,
    actor_key: str,
    persona_instance_id: str | None,
    archived_path: Path,
    resurrect: bool,
) -> None:
    """THE tombstone fence for ``upsert_actor`` (D1).

    Called only when there is NO live row, because a live row cannot be a
    resurrection whatever the ledger says about it.

    TWO pieces of evidence, either of which is enough. The archive COPY is
    the primary one; the ledger entry is kept beside it because the two can
    legitimately disagree — a realm-sync pull rewrites the surface without
    the archive file, and an archive file can be moved away by hand — and a
    fence that demanded both would be defeated by whichever half went
    missing first. That asymmetry is the whole live incident: the re-add
    cleared both, so by the time the retire replay looked, neither was left
    to prove the delete had ever happened.

    A method rather than an inline block for the reason the class-key fence
    is one: a fence with a NAME can be pinned by the source tests, reported
    on by the doctor, and — the case that forced it — neutralised on its own
    by a test isolating a DIFFERENT fence's claim. An inline block silently
    makes every such test measure two guards at once.
    """

    if resurrect:
        return
    archived_keys: list[str] = []
    try:
        archived_keys = list(store.get_surface(workspace_id).archived_actor_keys)
    except Exception:  # noqa: BLE001 - no surface is no ledger to consult
        archived_keys = []
    if not archived_path.exists() and actor_key not in archived_keys:
        return
    raise ActorArchived(
        f"actor_archived:{actor_key} was deleted on this server; drop the "
        "local row and place a new agent instead of re-adding this key "
        "(`harness office actor-restore`, or --resurrect, re-adds it "
        "deliberately)",
        safe_details={
            "actor_key": actor_key,
            "workspace_id": workspace_id,
            "persona_instance_id": persona_instance_id,
        },
    )


def _guard_class_keyed_write(store: OfficeStore, workspace_id: str, payload: dict[str, Any], *, allow_class_key: bool) -> None:
    """THE class-key fence for ``upsert_actor`` — one fence, at the store.

    Hoisted here from its four callers (Plan EG-6.6). It used to be called
    at ``serve_rpc._runtime_office_upsert``, ``agent_create``'s placement
    leg, ``harness office actor-upsert`` and ``workspace_template``'s copy —
    four copies of one decision around one store, which is why
    ``scripts/office_actor_rekey_to_instance.py`` had to WARN that a new
    writer reaching ``upsert_actor`` was unfenced by default. It was: the
    fifth caller would have shipped with the hole and every reply-shape test
    green, because a caller-side fence is invisible in the store's own
    contract.

    What the callers keep is a TRANSLATION of the refusal below into their
    transport's taxonomy (a 4090 with ``data.reason``, a stage-42
    ``duplicate_conflict`` exit, a copy warning, a compensated create
    failure) — never a second copy of the decision. The predicate itself
    still lives in ``office_class_key_guard``, one derivation authority.

    The refusal MESSAGE is the shared ``refusal_message`` verbatim, because
    three of those translations assert on it and because the operator-facing
    exits it names (send the binding, ``actor-restore``,
    ``--allow-class-key``) are the same three from every lane that has them.

    Fires on ``dry_run`` too. A preview whose whole job is to show what the
    real run would do must show the refusal, or the operator learns about it
    only from the write.
    """

    if allow_class_key:
        return
    from ..office_class_key_guard import (
        ClassKeyedPlacementRefused,
        class_key_collision,
        refusal_message,
    )

    collision = class_key_collision(store, workspace_id, payload)
    if collision is None:
        return
    raise ClassKeyedPlacementRefused(refusal_message(collision), safe_details=collision)


def _guard_class_keyed_adoption(store: OfficeStore, workspace_id: str, actor: OfficeActor, *, allow_class_key: bool) -> None:
    """The class-key fence for ``resolve_conflict(take="remote")``.

    That branch writes a PEER's actor with ``_write_actor`` DIRECTLY,
    bypassing ``upsert_actor`` and therefore its fence. So it can put an
    archived CLASS key back on disk as ACTIVE beside its instance-keyed
    sibling — the same double placement the re-key migration exists to
    remove, reached through the one door the fence did not cover.

    The SECOND of the store's two class-key fences, and it stays separate
    from ``_guard_class_keyed_write`` rather than merging into it: this one's
    input is a deserialized peer RECORD (whose ``actor_key`` is authoritative
    and whose spelling never met ``_normalize_actor_persona_ref``), not a caller's
    payload, and its refusal names a different exit (``--take local``). One
    predicate, two typed entrances — which is the shape that let this method
    be fenced at all, since its payload never passes ``upsert_actor``.

    Refuses, rather than silently re-keying the incoming actor onto the
    instance binding: that would rewrite what the peer published into a
    different identity (the next push sends back an actor the peer never
    had), and in the duplicate-item case it would land ON TOP of the
    migrated instance-keyed actor — trading a visible double placement for a
    silent clobber. ``allow_class_key`` is the operator's way through.

    Normalizes BOTH sides of the class-key test. This is the one path whose
    input never met ``_normalize_actor_persona_ref``, so a peer's ``Backend_Dev``
    arrives verbatim; a raw comparison would read it as instance-keyed and
    wave the write through.
    """

    if allow_class_key:
        return
    from ..office_class_key_guard import (
        ClassKeyedPlacementRefused,
        class_key_collision,
        refusal_message,
    )

    persona_id = _normalize_actor_persona_ref(actor.persona_id)
    if not persona_id or _normalize_actor_persona_ref(actor.actor_key) != persona_id:
        # Instance-keyed adoption: it IS the migration's shape, never undoes it.
        return
    collision = class_key_collision(
        store,
        workspace_id,
        # Deliberately class-keyed and deliberately UN-normalized: the guard
        # owns normalization (one derivation authority), and the key that
        # would actually be written is the class key regardless of what
        # ``persona_instance_id`` the peer's record happens to carry.
        {
            "persona_id": actor.persona_id,
            "items": [{"item_id": item.item_id} for item in actor.items],
        },
    )
    if collision is None:
        return
    # The shared ``refusal_message`` is left untouched (the upsert fence
    # raises it verbatim and three lanes assert on it); the
    # resolve-specific exit gets appended, because "--take local" is
    # the answer an operator under conflict pressure actually needs and the
    # shared message cannot know to offer it.
    raise ClassKeyedPlacementRefused(
        refusal_message(collision) + " Resolve with --take local to keep the migrated state.",
        safe_details={**collision, "take": "remote"},
    )
