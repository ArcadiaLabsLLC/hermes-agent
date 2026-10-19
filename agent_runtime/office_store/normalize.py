"""Write-time normalization of office payloads: actor refs, folders, display
names (validated against the realm-sync secret scanner), canonical actor keys,
item positions, minted kinds, and folder lists. Pure — no store, no I/O.
"""

from __future__ import annotations

from typing import Any

from agent_runtime import office_layout_policy, office_models
from agent_runtime.models import OfficeItem
# Eager, not lazy: the rule now lives in stdlib-only ``agent_runtime.redaction``,
# so importing it costs nothing. The old lazy ``from .realm_sync import …`` was
# dodging ``realm_sync``'s weight — the tell that ``realm_sync`` was the wrong
# home for a constant four other modules needed.
from agent_runtime.redaction import SECRET_ASSIGNMENT_RE
from agent_runtime.serde import safe_id
from agent_runtime.office_store.models import MAX_FOLDERS, ActorKind, ActorKindInvalid

__layer__ = "policy"

__all__ = [
    "_assert_display_name_publishable",
    "_canonical_actor_key",
    "_item_point",
    "_normalize_folders",
    "_normalize_item",
    "_normalize_actor_persona_ref",
    "_safe_actor_ref",
    "_safe_display_name",
    "_safe_folder",
    "normalize_actor_kind",
]

#: The payload word → its kind. Absent/blank is the default; anything else is refused, never guessed.
_ACTOR_KINDS = {kind.value: kind for kind in ActorKind}


def normalize_actor_kind(value: Any) -> ActorKind:
    """``actor_kind`` off an upsert payload: absent → ``PERSONA``; an unknown word →
    :class:`ActorKindInvalid` (``actor_kind_invalid``)."""
    text = str(value or "").strip().lower()
    if not text:
        return ActorKind.PERSONA
    kind = _ACTOR_KINDS.get(text)
    if kind is None:
        raise ActorKindInvalid(f"actor_kind_invalid: {text[:40]!r} is not one of {sorted(_ACTOR_KINDS)}")
    return kind


def _safe_actor_ref(value: Any, *, fallback: str = "operator") -> str:
    return safe_id(value) or fallback


def _normalize_actor_persona_ref(value: Any) -> str | None:
    # Mirrors the launcher's OfficeAgentIdentity normalization: trim + lower.
    text = str(value or "").strip().lower()
    return safe_id(text)


def _safe_folder(value: Any) -> str:
    return " ".join(str(value or "").split())[:80]


def _safe_display_name(value: Any) -> str | None:
    text = " ".join(str(value or "").split())[:120]
    return text or None


def _assert_display_name_publishable(name: str) -> None:
    """Typed write-time rejection of secret-shaped display names (plan §4.2).

    The realm-sync publish scan (`_assert_no_secret_artifacts`) hard-fails the
    WHOLE realm publish on a content match; rejecting at the write chokepoint
    keeps that scan defense-in-depth instead of the primary gate.
    """

    if SECRET_ASSIGNMENT_RE.search(name):
        raise ValueError("invalid_request: display_name looks like a secret assignment")


def _canonical_actor_key(persona_id: str, persona_instance_id: str | None) -> str:
    if persona_instance_id:
        from ..persona_assignments.identity import canonical_persona_instance_id  # single derivation authority

        canonical = canonical_persona_instance_id(persona_instance_id, persona_id=persona_id)
        if canonical:
            return canonical
    return persona_id


def _item_point(value: Any) -> tuple[float, float]:
    """The ``[x, y]`` a raw item carries, validated.

    Lifted out of :func:`_normalize_item` so the ONE caller that does not have a
    point yet — an unaimed placement, whose slot :meth:`OfficeStore.upsert_actor`
    resolves under its own lock — can hand the resolved one in without a second
    copy of these checks.
    """

    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("invalid_request: item position must be [x, y]")
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_request: item position must be numeric") from exc
    if x != x or y != y or abs(x) == float("inf") or abs(y) == float("inf"):
        raise ValueError("invalid_request: item position must be finite")
    return (x, y)


def _normalize_item(
    raw: Any, *, persona_id: str, position: tuple[float, float] | None = None
) -> OfficeItem:
    """One raw item dict as the store will persist it.

    ``position``, when supplied, is the RESOLVED point and OVERRIDES whatever
    the raw item carried — the unaimed lane's answer, computed inside
    ``office_lock`` by :meth:`OfficeStore.upsert_actor`'s ``position_policy``.
    Absent, the raw item must carry its own and :func:`_item_point` validates
    it, which is every other lane unchanged.

    A BLANK ``folder`` is filled with the kind's default HERE, at the write
    boundary (M9 / H-H9). It used to persist as ``""``, and one stored value
    then meant two things: three separate readers compensated for it
    independently — ``office_layout_policy.item_folder`` resolves it before
    scanning, the launcher's ``MissionOfficeSceneItem`` substitutes the default
    at decode, and a third reader compensated again — so "which folder is this
    item in" had three answers derived three ways from a value that said
    nothing. Filling it once, where the row is written, makes one stored row
    mean one thing.

    The READ-side fallbacks stay, and are not now redundant: rows written before
    this landed still hold ``""`` on disk, and ``office_sync.apply_office_pull``
    adopts a peer's actor files WITHOUT passing through this function, so a peer
    on an older hermes can still deliver one. The cross-repo fixture case
    ``blank_folder_falls_back_to_kind`` pins exactly that residue and is
    unchanged by this — what changes is that this store stops MINTING the shape.
    """

    if not isinstance(raw, dict):
        raise ValueError("invalid_request: item must be an object")
    item_id = safe_id(raw.get("item_id"))
    if not item_id:
        raise ValueError("invalid_request: item_id required")
    item_persona = _normalize_actor_persona_ref(raw.get("persona_id")) or persona_id
    x, y = position if position is not None else _item_point(raw.get("position"))
    display_name = _safe_display_name(raw.get("display_name"))
    if display_name:
        _assert_display_name_publishable(display_name)
    kind = office_models.normalize_item_kind(raw.get("kind"))
    # ``folder_for_kind``, not a local pair of constants: it is the SAME
    # authority the layout policy's own fallback spends, so the folder this
    # write persists and the folder that policy would have inferred cannot
    # disagree — which they could the moment a second spelling of "Agents"
    # existed.
    folder = _safe_folder(raw.get("folder")) or office_layout_policy.folder_for_kind(kind)
    return OfficeItem(
        item_id=item_id,
        persona_id=item_persona,
        kind=kind,
        position=[x, y],
        folder=folder,
        display_name=display_name,
        pet_slug=safe_id(raw.get("pet_slug")),
        scale=office_models.normalize_scale(raw.get("scale", office_models.SCALE_DEFAULT)),
    )


def _normalize_folders(values: Any) -> list[str]:
    folders: list[str] = [*office_models.DEFAULT_FOLDERS]
    if isinstance(values, (list, tuple)):
        for value in values:
            folder = _safe_folder(value)
            if folder and folder not in folders:
                folders.append(folder)
            if len(folders) >= MAX_FOLDERS:
                break
    return folders
