"""What is being asked, and is it well-formed: ``AgentCreateRequest`` and the
one validation walk (syntax, then the roster, then the position, then the
skills — in the order ``normalize_agent_create`` insists on), the persona
roster and its accepted spellings, and the honest default display name.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..models import (
    PLACEMENT_ID_NOT_DISCRIMINABLE_REASON,
    looks_like_deliberate_placement,
    placement_id_not_discriminable_message,
)
from ..persona_assignments.identity import (
    _display_name_for_template,
    _normalize_instance_source_persona,
)
from ..serde import safe_assignment_text, safe_assignment_token
from .outcome import (
    AgentCreateInvalid,
    DEFAULT_AGENT_FOLDER,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    PERSONA_NOT_FOUND_REASON,
    PERSONA_ROSTER_UNAVAILABLE_REASON,
    PersonaRosterUnavailable,
    persona_roster_unavailable_message,
)

__layer__ = "stores"


@dataclass(frozen=True)
class AgentCreateRequest:
    """A normalised create. Every field is already store-safe."""

    persona_id: str
    workspace_id: str
    #: ``None`` means the client did not aim — the layout policy chooses (D2).
    #: It is NOT a missing value to be defaulted somewhere later: the ONE site
    #: that resolves it is :func:`placement_position_policy`, and since H-H10 it
    #: runs INSIDE ``office_lock``, so the actor set it reads IS the set the
    #: write lands beside rather than the closest this lane could get to it.
    position: tuple[float, float] | None
    #: ``None`` means the client sent no ``skills`` key at all, and the new
    #: instance's ``skill_overrides`` stays ``None`` (inherit the persona's,
    #: live). A LIST — including an empty one — is an explicit assignment, and
    #: ``[]`` therefore means "override with nothing", which is a different
    #: agent from one that inherits. See :func:`_skills` (D5).
    skills: tuple[str, ...] | None
    idempotency_key: str
    placement_id: str
    display_name: str | None
    default_display_name: str
    realm_id: str | None
    folder: str
    correlation_id: str | None

    @property
    def persona_instance_id(self) -> str:
        from ..persona_assignments.identity import persona_instance_id_for_placement

        return persona_instance_id_for_placement(self.placement_id)


def honest_default_display_name(persona_id: str, persona: Any | None = None) -> str:
    """The name a create falls back to when the client sends none.

    The persona's configured ``display_name`` first ("QA Agent"), and only then
    the title-cased id. NEVER the store template's own fallback, which is the
    bare title-cased persona id and reads to an operator as a different agent.

    ``persona`` is optional so the CLI can pass the persona object it already
    resolved through its own richer ``_persona_by_id`` (preserving that lane's
    behaviour byte-for-byte) while the RPC lane, which has no such object, is
    answered by the importable lookup below. The lookup is a SUBSET of the CLI
    resolver, never a superset, so the two can only ever agree.
    """

    configured = (
        safe_assignment_text(getattr(persona, "display_name", None), limit=120)
        if persona is not None
        else ""
    )
    if configured:
        return configured
    resolved = resolve_persona(persona_id)
    configured = safe_assignment_text(
        getattr(resolved, "display_name", None), limit=120
    )
    if configured:
        return configured
    return _display_name_for_template(str(persona_id or ""))


def persona_roster() -> list[Any]:
    """Every persisted persona, or raise :class:`PersonaRosterUnavailable`.

    The STRICT half of the lookup. An EMPTY list is a real answer — a runtime
    that genuinely has no personas — and is distinct from a raise. That
    distinction matters more than it looks: UC-0 measured a hermetic root's
    default roster as empty, so "no personas" is a reachable state, not an
    impossible one, and a create against it should be refused rather than
    excused.
    """

    try:
        from ..config import ensure_persisted_personas, load_agent_runtime_config

        return list(ensure_persisted_personas(load_agent_runtime_config()))
    except Exception as exc:  # noqa: BLE001 — re-raised as a typed fault below
        raise PersonaRosterUnavailable(str(exc)) from exc


def resolve_persona(persona_id: str) -> Any | None:
    """The persisted persona for *persona_id*, or ``None``.

    Deliberately narrow: exact id, then the safe-token spelling. It does NOT
    synthesise a ``profile:`` persona the way the CLI's ``_persona_by_id`` does,
    because the only field this module reads off the result is
    ``display_name`` and a synthesised profile persona's is derived from the
    profile token — which is exactly what the fallback below computes anyway.
    Never raises: a config this process cannot load is "no persona", and the
    caller's fallback covers it.
    """

    try:
        personas = persona_roster()
    except PersonaRosterUnavailable:
        return None
    raw = str(persona_id or "").strip()
    token = safe_assignment_token(raw)
    for persona in personas:
        if getattr(persona, "id", None) == raw:
            return persona
    for persona in personas:
        if getattr(persona, "id", None) == token:
            return persona
    return None


#: How many placeable ids the refusal spells out before it stops and points at
#: the verb. A bound, not a preference: this string is an ERROR message on a
#: lane whose envelopes are read by a launcher panel, and a runtime with a
#: hundred personas must not turn a one-line refusal into a page. The live
#: operator root carries five, so the cap is dormant there and the list is
#: whole; it exists for the root that is not this one.
PERSONA_CHOICE_LIST_LIMIT = 20


def accepted_persona_spellings(persona: Any, roster: Sequence[Any]) -> list[str]:
    """Every spelling ``--persona`` accepts for *persona*, bare id first.

    The ONE authority for the question "how may an operator name this row",
    shared by :func:`persona_not_found_message`'s choice list and by the
    ``harness agent list`` row. Two spellings at most, and the second is
    CONDITIONAL on something the id alone cannot show.

    ``profile:<token>`` does not reach this roster at all — it reaches the CLI
    resolver's synthesis lane (``_persona_by_id``), which fills the synthesised
    persona's model/provider/toolsets from ``profile_persona_resolution``, and
    that returns a persona only for a profile with exactly ONE owner. So a
    profile two personas declare is deliberately NOT advertised here: the
    spelling still parses (D-U1 exempts every ``profile:`` id from the roster
    check), but it would mint a defaults-less agent DIFFERENT from the id
    printed beside it, and an error message that offers that trade silently is
    worse than one that offers nothing.
    """

    persona_id = str(getattr(persona, "id", "") or "").strip()
    spellings = [persona_id] if persona_id else []
    profile = str(getattr(persona, "hermes_profile", "") or "").strip()
    if not profile:
        return spellings
    owners = [
        str(getattr(row, "id", "") or "").strip()
        for row in roster
        if str(getattr(row, "hermes_profile", "") or "").strip() == profile
    ]
    profile_spelling = f"profile:{profile}"
    if owners == [persona_id] and profile_spelling not in spellings:
        spellings.append(profile_spelling)
    return spellings


def _placeable_persona_choice_text() -> str:
    """The refusal's choice list, or ``""`` when there is nothing to offer.

    Best-effort ON PURPOSE. It is reached only after a refusal has already been
    decided, so a roster this second read cannot open must degrade the message
    back to its cure sentence rather than convert a refusal the caller can act
    on into a fault it cannot — the exact collapse
    :class:`PersonaRosterUnavailable` exists to prevent, one layer out.
    """

    try:
        roster = list(persona_roster())
    except PersonaRosterUnavailable:
        return ""
    listed: list[str] = []
    for persona in roster:
        spellings = accepted_persona_spellings(persona, roster)
        if not spellings:
            continue
        listed.append(
            spellings[0] + (f" (or {spellings[1]})" if len(spellings) > 1 else "")
        )
    if not listed:
        return ""
    shown = listed[:PERSONA_CHOICE_LIST_LIMIT]
    remainder = len(listed) - len(shown)
    return "; ".join(shown) + (f"; and {remainder} more" if remainder else "")


def persona_not_found_message(persona_id: Any) -> str:
    """The ONE spelling of the refusal, shared by every lane (UC-H2/UC-H4).

    It names the cure, because the operator who hits this has usually typed a
    plausible-looking id (``qa_agent`` for ``qa``) and has no way to know the
    roster from the error alone.

    Since 2026-09-02 it also names the CHOICES. Naming the verb was the whole
    cure while the operator was at a console with a shell; it is not one for a
    script, a cron or a remote ``call`` leg, none of which can run a second
    command to find out what the first would have accepted. Both accepted
    spellings ride along for the same reason ``--persona`` takes two: ``qa``
    and ``profile:launcher-qa`` are the same agent, and nothing else in the
    CLI says so.
    """

    base = (
        f"unknown persona: {str(persona_id or '')!r} is not in the agent roster; "
        "run `harness agent list` to see the personas that exist, or add it "
        "before creating an instance for it"
    )
    choices = _placeable_persona_choice_text()
    return f"{base}. Placeable now: {choices}" if choices else base


def _persona_is_unknown(persona_id: str, persona: Any | None = None) -> bool:
    """Does this create name a persona that does not exist?

    Decision **D-U1**, and it is load-bearing: a ``profile:``-prefixed id is
    deliberately NOT checked. The launcher's template/preset browser sends
    ``profile:<token>`` ids for profiles that own no persona row at all, and
    the CLI's ``_persona_by_id`` SYNTHESISES a persona for them on purpose
    (``profile_persona_resolution`` returns ``None`` matches without raising).
    Making validation uniform would break that lane silently, since nothing
    else covers it — so the carve-out has its own witness test.

    ``persona`` is the caller's already-resolved persona object. The CLI
    resolver is a strict SUPERSET of :func:`resolve_persona` (it also handles
    profile synthesis and instance-id spellings), so "the caller found one"
    settles the question without a second, narrower lookup contradicting it.

    Asks :func:`persona_roster` rather than :func:`resolve_persona`, and the
    difference is the whole point. ``resolve_persona`` answers ``None`` for BOTH
    "no such persona" and "this process could not read the config" — correct for
    its original job (a display-name fallback, where either miss is harmless)
    and WRONG here, where the answer decides whether a durable write is refused.
    Routed through the forgiving lookup, an unreadable config would refuse every
    bare-id create on every lane with a message blaming the operator's id.

    So this raises :class:`PersonaRosterUnavailable` instead of returning
    ``True``. A fault the caller cannot act on must not wear the costume of a
    refusal the caller can.
    """

    if persona is not None:
        return False
    if str(persona_id or "").lower().startswith("profile:"):
        return False
    raw = str(persona_id or "").strip()
    token = safe_assignment_token(raw)
    personas = persona_roster()  # raises PersonaRosterUnavailable
    return not any(
        getattr(persona_row, "id", None) in (raw, token) for persona_row in personas
    )


def require_known_persona(
    persona_id: str, persona: Any | None = None
) -> dict[str, Any] | None:
    """The argv lanes' shape of the same refusal, or ``None`` to proceed.

    The unified lane raises :class:`AgentCreateInvalid` from
    :func:`normalize_agent_create`; the legacy ``persona instance`` verbs print
    an ``{"ok": false, …}`` payload and exit 2. Same predicate, same message,
    same D-U1 carve-out — one spelling, two envelopes.
    """

    try:
        unknown = _persona_is_unknown(persona_id, persona)
    except PersonaRosterUnavailable as exc:
        return {
            "ok": False,
            "error": persona_roster_unavailable_message(exc),
            "reason": PERSONA_ROSTER_UNAVAILABLE_REASON,
            "persona_id": persona_id,
            "next_expected": (
                "run `harness doctor` to find why the agent roster cannot be "
                "read, then re-run — the persona id is not the problem"
            ),
        }
    if not unknown:
        return None
    return {
        "ok": False,
        "error": persona_not_found_message(persona_id),
        "reason": PERSONA_NOT_FOUND_REASON,
        "persona_id": persona_id,
        "next_expected": (
            "run `harness agent list` to see the personas that exist, then "
            "re-run with one of them"
        ),
    }


def mint_placement_id(persona_id: str) -> str:
    """A server-side placement id, shaped like the launcher's own.

    The launcher normally mints this itself (``missionMintDeliberatePlacementId``)
    and sends it, so this is the fallback for a caller that only knows "put a
    <persona> at (x, y)". The hex tail is what keeps two rapid creates of one
    persona distinct — the id is IDENTITY, and the cosmetic "(2)" suffix is a
    separate concern that stays with the client (decision D-A1).

    The ``_agent_`` marker is not decoration: it is what
    ``DELIBERATE_PLACEMENT_SUFFIX`` matches, and it was MISSING here until
    2026-08-27. This function claimed parity with the launcher mint and did not
    have it, so every server-minted placement derived an instance id the
    launcher classified as a conversational channel — the wrong-alice incident
    reached through the door that requires no operator input at all.
    """

    token = safe_assignment_token(persona_id) or "persona"
    return f"{token}_agent_{uuid.uuid4().hex[:8]}"


def _position(value: Any) -> tuple[float, float] | None:
    """The operator's aim, or ``None`` when there was none (plan D2).

    ``None`` — an omitted key or an explicit JSON ``null`` — is ABSENCE, and
    absence is a legal request answered by the layout policy. It used to refuse
    ``position_invalid``, which is why ``--pos`` was required and why every door
    without a canvas had nothing to send.

    Treating explicit ``null`` as absence rather than as a malformed value is
    the deliberate half of that: a JSON client that spells "no opinion" as
    ``null`` means the same thing as one that omits the key, and refusing one
    while accepting the other would make the wire's meaning depend on a
    serializer's `omit-none` setting.

    Everything else refuses exactly as before — a one-element list, a string, a
    bool pair, an infinity — because those are an aim that did not survive
    transport, not the absence of one.
    """

    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise AgentCreateInvalid(
            "position_invalid", "invalid params: position must be [x, y]"
        )
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError) as exc:
        raise AgentCreateInvalid(
            "position_invalid", "invalid params: position must be numeric"
        ) from exc
    # ``bool`` is an ``int``: ``[True, False]`` would otherwise place an agent
    # at (1.0, 0.0) and read as a deliberate placement forever.
    if isinstance(value[0], bool) or isinstance(value[1], bool):
        raise AgentCreateInvalid(
            "position_invalid", "invalid params: position must be numeric"
        )
    if x != x or y != y or abs(x) == float("inf") or abs(y) == float("inf"):
        raise AgentCreateInvalid(
            "position_invalid", "invalid params: position must be finite"
        )
    return (x, y)


#: The instance store's own override cap (``_safe_skill_overrides`` slices to
#: 40), re-spelled as a REFUSAL rather than inherited as a silent truncation: a
#: create whose 41st skill vanished on the way to the store would report
#: ``assigned`` with 41 entries and hold 40.
MAX_SKILLS = 40


def _skills(value: Any) -> tuple[str, ...] | None:
    """The requested skill ids, or ``None`` when the client sent no opinion.

    SHAPE only. Whether an id RESOLVES — and whether its installed copy matches
    the repo's — is the skills PHASE's question, asked after the placement, and
    it must be: a refusal here refuses before any write, and D4 rules that a
    skills fault never costs an agent its placement.

    Absence and ``null`` both mean inherit, for the same reason
    :func:`_position` reads them as one: a client spelling "no opinion" as
    ``null`` means what one omitting the key means, and the wire's meaning must
    not depend on a serializer's omit-none setting. An empty LIST is not
    absence — it is an explicit "no skills", recorded as ``[]``.

    Every member is stringified and stripped; blanks are dropped and duplicates
    collapse to their first appearance, which is the store's own
    ``_safe_skill_overrides`` behaviour re-spelled so the ack's ``assigned``
    list is the list that was written rather than a superset of it.
    """

    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise AgentCreateInvalid(
            "skills_invalid", "invalid params: skills must be a list of skill ids"
        )
    ids: list[str] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            # A dict/list/None member is a client that built the wrong payload,
            # not a skill nobody has: refusing it here is honest, and letting it
            # through as ``str(item)`` would place an agent and then refuse the
            # skills phase on an id spelled ``{'id': 'x'}``.
            raise AgentCreateInvalid(
                "skills_invalid",
                "invalid params: every skills entry must be a skill id string",
            )
        text = str(item).strip()
        if not text or text in ids:
            continue
        ids.append(text)
    if len(ids) > MAX_SKILLS:
        raise AgentCreateInvalid(
            "skills_invalid",
            f"invalid params: skills must name {MAX_SKILLS} ids or fewer",
        )
    return tuple(ids)


def normalize_agent_create(
    params: dict[str, Any], *, persona: Any | None = None
) -> AgentCreateRequest:
    """Validate + normalise one create request. Raises :class:`AgentCreateInvalid`.

    Runs BEFORE any store is touched, so a refusal here provably wrote nothing.
    That property is why the roster check (UC-H2) belongs here and not in the
    store: until this returns, the create has left no roster row, no chat root,
    no placement and no reservation receipt to clean up.
    """

    persona_raw = params.get("persona_id")
    if not isinstance(persona_raw, str) or not persona_raw.strip():
        raise AgentCreateInvalid(
            "persona_id_required",
            "invalid params: persona_id must be a non-empty string",
        )
    # ``_normalize_instance_source_persona`` COLLAPSES an unusable id to the
    # literal token ``persona`` rather than refusing, which is right for the
    # send path (it must never drop a turn) and wrong here: it would mint a
    # durable roster row and a placement for an agent class nobody asked for.
    # So the collapse is detected before it happens, on the same tokenizer.
    if not safe_assignment_token(
        persona_raw.split(":", 1)[1]
        if persona_raw.strip().lower().startswith("profile:")
        else persona_raw
    ):
        raise AgentCreateInvalid(
            "persona_id_required",
            "invalid params: persona_id must be a non-empty string",
        )
    persona_id = _normalize_instance_source_persona(persona_raw)
    # UC-H2. Syntax first, roster second, and in that order deliberately: an
    # unusable id is a client bug with its own reason string, and re-labelling
    # it ``persona_not_found`` would send the launcher's decoder down the wrong
    # branch. Everything above this line is still pure string work, so this is
    # the FIRST question asked of the world — and it is asked here, in the one
    # function that provably runs before any store is touched, rather than in
    # the store (``add_instance`` is also the restore/rebind chokepoint, and
    # refusing there would need an audit of every historical row's persona id).
    try:
        persona_unknown = _persona_is_unknown(persona_id, persona)
    except PersonaRosterUnavailable as exc:
        # A fault, not a bad id — and it keeps its own reason all the way to the
        # client so a decoder can tell "fix your id" from "fix your runtime".
        raise AgentCreateInvalid(
            PERSONA_ROSTER_UNAVAILABLE_REASON,
            persona_roster_unavailable_message(exc),
        ) from exc
    if persona_unknown:
        raise AgentCreateInvalid(
            PERSONA_NOT_FOUND_REASON, persona_not_found_message(persona_id)
        )

    workspace_raw = params.get("workspace_id")
    workspace_id = (
        workspace_raw.strip() if isinstance(workspace_raw, str) else ""
    )
    if not workspace_id:
        # The same reason string the office legs spend, on purpose: one client
        # branch covers "the launcher forgot the workspace" on every method.
        raise AgentCreateInvalid(
            "workspace_id_required",
            "invalid params: workspace_id must be a non-empty string",
        )

    position = _position(params.get("position"))
    skills = _skills(params.get("skills"))

    key_raw = params.get("idempotency_key")
    idempotency_key = key_raw.strip() if isinstance(key_raw, str) else ""
    if not idempotency_key:
        raise AgentCreateInvalid(
            "idempotency_key_required",
            "invalid params: idempotency_key must be a non-empty string",
        )
    if len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise AgentCreateInvalid(
            "idempotency_key_invalid",
            "invalid params: idempotency_key must be "
            f"{MAX_IDEMPOTENCY_KEY_LENGTH} characters or fewer",
        )

    raw_placement = params.get("placement_id")
    if raw_placement is None:
        placement_id = mint_placement_id(persona_id)
    else:
        placement_id = safe_assignment_token(raw_placement)
        if not placement_id:
            # The CLI's own refusal, kept rather than softened to a mint: a
            # client that SENT a placement id is predicting an actor key from
            # it, and quietly substituting another one strands that prediction.
            raise AgentCreateInvalid(
                "placement_id_invalid",
                "invalid params: placement_id must be a non-empty token when sent",
            )
        # Asked of the SENT id only. A minted id clears this by construction,
        # and an id that reaches the store from anywhere else is a row that
        # already exists — this fence validates operator input, it does not
        # police the id space.
        if not looks_like_deliberate_placement(placement_id):
            raise AgentCreateInvalid(
                PLACEMENT_ID_NOT_DISCRIMINABLE_REASON,
                placement_id_not_discriminable_message(placement_id),
            )

    display_name = safe_assignment_text(params.get("display_name"), limit=120) or None

    realm_raw = params.get("realm_id")
    realm_id = safe_assignment_token(realm_raw) or None if realm_raw is not None else None

    folder = safe_assignment_text(params.get("folder"), limit=80) or DEFAULT_AGENT_FOLDER

    correlation_raw = params.get("correlation_id")
    correlation_id = (
        safe_assignment_text(correlation_raw, limit=200) or None
        if correlation_raw is not None
        else None
    )

    return AgentCreateRequest(
        persona_id=persona_id,
        workspace_id=workspace_id,
        position=position,
        skills=skills,
        idempotency_key=idempotency_key,
        placement_id=placement_id,
        display_name=display_name,
        default_display_name=honest_default_display_name(persona_id, persona),
        realm_id=realm_id,
        folder=folder,
        correlation_id=correlation_id,
    )
