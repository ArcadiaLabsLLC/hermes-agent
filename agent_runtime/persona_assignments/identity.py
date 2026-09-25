"""Persona and persona-instance identity: the id derivations, the canonical
chat-session ids and their owners, and the persona/template field derivations.

The seam most of the tree takes; it reads ``paths``/``models``/``personas`` and
never a store (the answers that need the roster are in ``lookups``).
"""

from __future__ import annotations

import uuid
from typing import Any

from agent_runtime.agent_create_phases import timed_create_subphase
from agent_runtime.models import PERSONA_INSTANCE_ID_PREFIX, PersonaInstance
from agent_runtime.persona_assignments.tokens import (
    safe_assignment_text,
    safe_assignment_token,
)

__layer__ = "policy"

__all__ = [
    "canonical_chat_instance_id",
    "canonical_persona_instance_id",
    "chat_session_is_foreign_to_instance",
    "chat_session_owner_instance_id",
    "is_canonical_persona_channel",
    "normalize_persona_id",
    "persona_chat_session_id_for",
    "persona_instance_id_for",
    "persona_instance_id_for_placement",
    "row_is_canonical_persona_channel",
    "_ACTOR_TOKEN_DRIFT_PREFIX",
    "_CHAT_SESSION_HEX_SUFFIX_LEN",
    "_coerce_travel_value",
    "_display_name_for_template",
    "_durable_chat_root",
    "_MISSING_TRAVEL_FIELD",
    "_normalize_instance_source_persona",
    "_PERSONA_CHAT_SESSION_PREFIX",
    "_profile_id_for_persona_or_template",
    "_role_for_persona_or_template",
]


# ``PERSONA_INSTANCE_ID_PREFIX`` / ``looks_like_persona_instance_id`` are the
# single id-shape authority, defined in ``models`` (the low layer the store row
# lives in) and imported at the top of this module. Re-exported here verbatim so
# existing ``from .persona_assignments import PERSONA_INSTANCE_ID_PREFIX``
# callers (harness.py, persona_commands.py) keep resolving through one home.

# An operator-channel actor token ('persona_' + instance id) that leaked into
# a store row id. Live evidence 2026-07-10: persona_personainst_neko_supervisor
# persisted beside personainst_neko_supervisor for the same channel.
_ACTOR_TOKEN_DRIFT_PREFIX = f"persona_{PERSONA_INSTANCE_ID_PREFIX}"


def persona_instance_id_for(persona_id: str) -> str:
    return f"{PERSONA_INSTANCE_ID_PREFIX}{safe_assignment_token(persona_id) or 'persona'}"


def persona_instance_id_for_placement(placement_id: str) -> str:
    return f"{PERSONA_INSTANCE_ID_PREFIX}{safe_assignment_token(placement_id) or 'persona'}"


def row_is_canonical_persona_channel(instance_id: Any, persona_id: Any) -> bool:
    """:func:`is_canonical_persona_channel`, asked of two STRINGS.

    THE derivation; the typed predicate below delegates to it. A second shape
    was needed by the reconciler's unplaced-instance classifier, which is pure
    over ``to_jsonable`` rows and must not re-spell "is this the operator's own
    channel" — getting that wrong in either direction reaps a chat channel or
    spares a ghost, and two spellings of one question are free to drift into
    disagreeing about which."""
    token = safe_assignment_token(persona_id)
    if not token:
        return False
    return str(instance_id or "").strip() == persona_instance_id_for(str(persona_id))


def is_canonical_persona_channel(instance: PersonaInstance) -> bool:
    """True when a row IS the persona/profile's canonical operator channel.

    The canonical channel is the global-singleton id
    ``persona_instance_id_for(persona_id)`` (e.g. ``personainst_qa`` for persona
    ``qa``, ``personainst_profile_alice`` for ``profile:alice``). A
    placement-backed or otherwise deliberate instance carries a distinct
    placement-derived id (``personainst_qa_agent_2``) whose tail is the scene
    itemId, so it never collapses onto the canonical id — that is exactly the
    discriminator the retire verb uses to protect the queued global-singleton
    redesign while ending placement-backed rows.

    NOT an id-SHAPE test, and that is why it survives the class of defect the
    launcher's archive lane hit on 2026-09-11: it asks whether THIS id is the
    one the persona's own channel would be minted under, so an instance minted
    by ``persona instance create`` (``personainst_chara_a2_7b31d0e4``, no
    ``_agent_`` marker) answers False correctly rather than being mistaken for a
    channel because its tail looks wrong."""
    return row_is_canonical_persona_channel(instance.id, instance.persona_id)


def canonical_persona_instance_id(raw_id: Any, *, persona_id: str | None = None) -> str | None:
    """SINGLE derivation authority for a caller-supplied persona-instance id.

    Every path that accepts an instance id from outside the store (operator
    chat opens, assignment specs, CLI verbs) must resolve it through here
    before minting or joining a row. The store historically persisted the
    same logical channel under four id schemes because callers' tokens were
    written through verbatim; this collapses the two schemes that are
    structurally recognizable:

    - ``persona_personainst_x`` (actor-token drift) -> ``personainst_x``
    - ``persona:<persona_id>`` selector tokens (launcher idle-row ids,
      mangled to ``persona_<persona_id>``) -> the persona's canonical
      operator-channel id.

    The legacy ``personainst_operator_<hash>`` scheme is not structurally
    derivable; the store reconciler (persona_instance_identity.py) retires
    those rows and records their aliases.
    """
    token = safe_assignment_token(raw_id)
    if not token:
        return None
    while token.startswith(_ACTOR_TOKEN_DRIFT_PREFIX):
        token = token[len("persona_") :]
    if persona_id:
        persona_token = safe_assignment_token(persona_id)
        if persona_token and token == f"persona_{persona_token}":
            return persona_instance_id_for(persona_id)
    return token


def persona_chat_session_id_for(persona_instance_id: str) -> str:
    normalized = safe_assignment_token(persona_instance_id) or "persona"
    return f"persona_chat_{normalized}_{uuid.uuid4().hex[:12]}"


def _durable_chat_root(
    session_id: str,
    *,
    persona_id: str,
    display_name: str | None = None,
) -> str:
    """The chat root, PERSISTED, on its way into the bind — or nothing binds.

    ``persona_chat_session_id_for`` returns a bare ``uuid4`` string; it creates
    nothing. Until 2026-08-20 the two mint fallbacks above handed that string
    straight to :meth:`PersonaInstanceStore.open_chat`, and only the argv
    handlers in ``hermes_cli`` ever made the row durable afterwards. The
    one-call create lane (``agent_runtime.agent_create``, which is what the
    launcher's drag-drop reaches over RPC) had no such step and could not have
    one — the durability helper lived in a CLI part ``agent_runtime`` must not
    import. So a dragged-in agent got a pointer to a transcript root that
    existed in the instance row, the create reservation and the read-model, and
    in no SessionDB at all; every send was then refused forever with
    ``unknown_chat_session``, because
    :func:`resolve_default_chat_session_id_for_instance` re-offers a
    chat-shaped own-instance pointer without ever checking that it resolves.

    Wrapping the id at the bind ARGUMENT (rather than calling an ensure step
    beside it) is deliberate: the pointer cannot be bound without this function
    having returned, so the ordering is structural rather than remembered.

    Raises :class:`PersonaChatPersistenceError` when the transcript store
    cannot be reached or the row cannot be written — the mint fails loudly and
    binds nothing, which is what the argv lane's ``chat_session_persist_failed``
    frame has always meant and what ``perform_agent_create`` now compensates.

    Lazy import: ``persona_chat_durability`` imports this module, so a
    module-level import here would close the cycle.
    """

    from ..persona_chat_durability import ensure_durable_persona_chat_root

    title = safe_assignment_text(display_name, limit=120)
    # Timed HERE rather than around the call site, because the call site is an
    # ARGUMENT expression and hoisting it into a local to wrap it would undo the
    # structural ordering this function's docstring is about.
    with timed_create_subphase("chat_root_ms"):
        return ensure_durable_persona_chat_root(
            session_id,
            persona_id=persona_id,
            title=f"{title} chat" if title else None,
        )


# A chat session id is, by construction, ``persona_chat_<instance>_<hex>`` (see
# ``persona_chat_session_id_for``) or a legacy ``persona_chat_*`` id. Reusing a
# chat lane must never thread onto a task/worker session id, so the reuse guard
# keys on this prefix.
_PERSONA_CHAT_SESSION_PREFIX = "persona_chat_"

# A minted chat session ends in a bare 12-hex suffix (``uuid4().hex[:12]``); the
# body between the prefix and that suffix is the OWNING instance id. This is the
# same exact-mint discrimination ``agent_chat_open`` uses to keep a sibling's
# session (``persona_chat_<inst>_agent_2_<hex>``) from being swallowed by the
# primary's ``persona_chat_<inst>_`` prefix.
_CHAT_SESSION_HEX_SUFFIX_LEN = 12


def chat_session_owner_instance_id(session_id: str | None) -> str | None:
    """The persona-instance id a minted chat session belongs to, or ``None``.

    ``persona_chat_<instance>_<12 hex>`` → ``<instance>``. A legacy/opaque
    ``persona_chat_*`` id whose tail is not a bare 12-hex block has no derivable
    owner and returns ``None`` (treated as un-owned, never foreign)."""
    token = safe_assignment_text(session_id, limit=200)
    if not token or not token.startswith(_PERSONA_CHAT_SESSION_PREFIX):
        return None
    body = token[len(_PERSONA_CHAT_SESSION_PREFIX) :]
    owner, sep, tail = body.rpartition("_")
    if (
        sep
        and owner
        and len(tail) == _CHAT_SESSION_HEX_SUFFIX_LEN
        and all(ch in "0123456789abcdef" for ch in tail.lower())
    ):
        return owner
    return None


def chat_session_is_foreign_to_instance(session_id: str | None, instance_id: str | None) -> bool:
    """True when ``session_id`` is a chat session MINTED FOR a DIFFERENT instance.

    Chat sessions encode their owning instance, so a session whose exact-mint
    owner resolves to some OTHER real ``personainst_*`` instance must never be
    adopted as ``instance_id``'s default chat lane nor bound onto its pointer —
    that sibling-session steal is what folded two live QA instances onto one
    operator channel and overwrote the canonical instance's default-chat pointer
    with a placement sibling's session (live 2026-07-18).

    Deliberately narrow to avoid false positives: only an owner that is itself a
    canonical ``personainst_*`` handle counts. Legacy/seed/opaque sessions whose
    middle token is a bare persona id (``persona_chat_qa_<hex>``) or a synthetic
    seed (``persona_chat_seed_<hex>``) have no real sibling to steal from and bind
    freely, as does a session this instance already owns."""
    owner = chat_session_owner_instance_id(session_id)
    if owner is None or not owner.startswith(PERSONA_INSTANCE_ID_PREFIX):
        return False
    target = safe_assignment_token(instance_id)
    return bool(target) and owner != target


def canonical_chat_instance_id(persona_id: str, persona_instance_id: str | None = None) -> str:
    """Canonical persona-instance id a chat lane threads onto.

    One derivation shared by every chat-session resolver here (default resolve,
    non-minting resolve, mint) so an instance-shaped target and a bare persona id
    always land on the SAME instance row — no variant rows, no parallel scheme.
    """
    return (
        canonical_persona_instance_id(persona_instance_id, persona_id=persona_id)
        if persona_instance_id
        else None
    ) or persona_instance_id_for(persona_id)


def _display_name_for_template(profile: str) -> str:
    return " ".join(part.capitalize() for part in profile.replace("_", "-").split("-") if part) or "Profile"


def _normalize_instance_source_persona(persona_or_template_id: str) -> str:
    raw = str(persona_or_template_id or "").strip()
    if raw.lower().startswith("profile:"):
        profile = safe_assignment_token(raw.split(":", 1)[1])
        return f"profile:{profile}" if profile else "profile:persona"
    return safe_assignment_token(raw) or "persona"


def normalize_persona_id(persona_id: str) -> str:
    """The one persona-id tokenizer every chat entry point spends.

    Moved here from ``hermes_cli/harness_parts/persona_commands.py`` (where it
    was ``_normalize_cli_persona_id``) with its behaviour unchanged: it is a
    pure function of this module's own primitives, and the durability step that
    now runs inside ``add_instance``/``create_operator_chat`` needs it from
    ``agent_runtime`` rather than from a CLI part that ``agent_runtime`` must
    never import. The CLI keeps the old private name as an alias, so its call
    sites are byte-identical.
    """

    value = safe_assignment_token(persona_id)
    if not value:
        raise ValueError(f"unsupported persona {persona_id!r}")
    return value


#: Sentinel for "the remote body did not carry this travelling key", kept
#: distinct from ``None`` because ``None`` is a MEANING on this record ("inherit
#: the backing persona live" for the override tier, "runtime-global" for the
#: scope pointers). Collapsing the two would make an omitted key and an
#: explicitly cleared one indistinguishable to the adopt arm.
_MISSING_TRAVEL_FIELD = object()


def _coerce_travel_value(name: str, value: Any) -> Any:
    """One pulled travelling value, coerced to the field's own type.

    The wire carries ``model_override_issued_at`` as an ISO-8601 string (that is
    what ``serde.to_jsonable`` writes and what ``from_jsonable`` reads back), and
    a supersession clock stored as a raw string would compare as text against
    every ``datetime`` beside it. Coercion goes through ``serde`` rather than a
    local ``fromisoformat`` so the wire spelling has exactly one parser.
    """

    if value is None:
        return None
    from typing import get_type_hints

    from ..serde import _coerce

    annotation = get_type_hints(PersonaInstance).get(name)
    if annotation is None:
        return value
    try:
        return _coerce(annotation, value)
    except Exception:  # noqa: BLE001 — an uncoercible value stays as it arrived
        return value


def _role_for_persona_or_template(persona_or_template_id: str) -> str | None:
    """The ROLE a replica should be stamped with — from the local persona
    definition, never from the wire.

    The sibling of :func:`_profile_id_for_persona_or_template` directly below,
    and it exists for the sharper of the two reasons: the persona definition
    arrives in the SAME pull (``apply_persona_config_pull`` runs before the
    instance lane), so travelling ``role`` would let a peer's stale copy shadow
    the definition that landed beside it. Unresolvable personas yield ``None``
    and the caller stamps ``""`` — a replica with no role is honest, where a
    replica with a wrong one is not.
    """

    raw = str(persona_or_template_id or "").strip()
    if not raw:
        return None
    try:
        from ..config import ensure_persisted_personas, load_agent_runtime_config

        for candidate in ensure_persisted_personas(load_agent_runtime_config()):
            if safe_assignment_token(getattr(candidate, "id", None)) == safe_assignment_token(raw):
                return str(getattr(candidate, "role", "") or "") or None
    except Exception:
        return None
    return None


def _profile_id_for_persona_or_template(persona_or_template_id: str) -> str | None:
    """The profile an instance projection should be stamped with at creation.

    B-4. This function used to answer ``None`` for every id that was not a
    synthetic ``profile:<name>`` channel — which is to say, for every real
    persona. That is the factory that mints null ``profile_id`` projections: the
    live store carries one (``personainst_qa_agent_644595cc``, persona ``qa``,
    whose persona binds ``launcher-qa``).

    Now it resolves through the persona's own ``hermes_profile``, so a new
    instance is stamped EXPLICITLY with the same profile its persona already
    binds.

    NOT a resolution change. ``profile_id`` on an instance is a PROJECTION, and
    A-3 verified that nothing on the turn path reads it: every one of
    ``resolve_persona_profile``'s call sites takes a PERSONA, and the run path
    (``persona_runtime.py:142``) takes the persona binding. The one consumer
    that displays it (``persona_instance_summary``) already falls back with
    ``instance.profile_id or persona.hermes_profile``, so the rendered value is
    identical before and after. What changes is that the row now STATES the fact
    instead of leaving a reader to re-derive it.

    Unresolvable personas still yield ``None`` — a null binding remains
    supported and is not an error.
    """
    raw = str(persona_or_template_id or "").strip()
    if raw.lower().startswith("profile:"):
        return safe_assignment_token(raw.split(":", 1)[1]) or None
    if not raw:
        return None
    try:
        from ..config import ensure_persisted_personas, load_agent_runtime_config

        for candidate in ensure_persisted_personas(load_agent_runtime_config()):
            if safe_assignment_token(getattr(candidate, "id", None)) == safe_assignment_token(raw):
                return safe_assignment_token(getattr(candidate, "hermes_profile", None)) or None
    except Exception:
        # A store/config read failure must never block minting an instance.
        # Falling back to None reproduces exactly the previous behaviour.
        return None
    return None
