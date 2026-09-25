"""The create's VOCABULARY and errors (layout sheet agent_create.md §1).

The JSON-RPC codes this service answers in (re-spelled from ``serve_rpc``,
fenced by test), the ``data.phase`` words, the persona reasons, the
reservation-fault stamps, the three exceptions, the outcome shapes and
their one constructor, and the skills-refusal renderer. A vocabulary +
errors module, exempt from the 100-line floor by kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__layer__ = "models"

#: The store's own first default folder, reused rather than re-spelled.
DEFAULT_AGENT_FOLDER = "Agents"

#: Same bound the chat-mint ledger enforces (``persona_chat_mints._validated_key``).
MAX_IDEMPOTENCY_KEY_LENGTH = 240


class AgentCreateInvalid(ValueError):
    """A create request this lane refuses before touching any store.

    ``reason`` is the machine-readable branch point a client switches on; the
    message is prose for an operator and is free to change.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class PersonaRosterUnavailable(RuntimeError):
    """The agent roster could not be READ. A runtime fault, not a bad id.

    The distinction exists because UC-H2 made the roster load-bearing. Before
    it, a config this process could not read degraded quietly to a title-cased
    display name and nothing else noticed. After it, the same fault would have
    turned EVERY bare-id create on EVERY lane into ``persona_not_found`` — an
    error that names the operator's id as the problem when the id was fine and
    the runtime is the problem. An operator reading that would go looking for a
    typo that does not exist.

    So the two are separated at the source. "The roster says this persona does
    not exist" is a refusal the caller can act on; "the roster could not be
    read" is a fault the caller cannot act on, and it gets its own reason.
    Neither degrades to the other, and neither degrades to silence — which is
    the standing rule that a missing answer is a LOUD error, never a quiet
    guess.
    """


#: The machine-readable branch point for "that persona names nothing".
PERSONA_NOT_FOUND_REASON = "persona_not_found"

#: The machine-readable branch point for "the roster could not be read at all".
#:
#: A SEPARATE reason rather than a flavour of the one above, because the two
#: need opposite responses: ``persona_not_found`` means the caller should send a
#: different id, and this one means the caller should send the SAME id once the
#: runtime is healthy. Collapsing them would send an operator hunting a typo
#: that does not exist — and would send a client's retry logic the wrong way.
PERSONA_ROSTER_UNAVAILABLE_REASON = "persona_roster_unavailable"


def persona_roster_unavailable_message(cause: Any = None) -> str:
    """The ONE spelling of the roster-fault refusal, shared by every lane.

    Names the runtime as the subject, never the id — the id was fine.
    """

    detail = str(cause or "").strip()
    return (
        "the agent roster could not be read, so this create was refused "
        "before touching any store; the persona id is not the problem"
        + (f" ({detail})" if detail else "")
    )


# ── the shared create sequence (UC-H1) ───────────────────────────────────────

# The JSON-RPC error codes this service answers in. Re-spelled here rather than
# imported from ``serve_rpc`` on purpose: importing that module would drag the
# entire method registry (and its store imports) into every CLI process that
# only wants to create one agent, and would invert the dependency — serve_rpc
# imports THIS module. Drift is fenced instead of prevented:
# ``tests/agent_runtime/test_agent_create_service.py`` asserts each constant
# equals ``serve_rpc``'s same-named one, so a change to either goes red.
ERR_INVALID_PARAMS = -32602
ERR_HANDLER_FAILED = -32000
ERR_NOT_FOUND = 4001
ERR_CONFLICT = 4090

# ── ``data.phase``: WHICH half of the two-write sequence a refusal failed in ──
#
# The launcher's ``MissionAgentCreateFault.phase`` documents exactly three
# values — ``instance | placement | null`` — and its parser is
# ``dataMap?['phase']?.toString()``, i.e. it accepts any string and renders it
# verbatim into the drop log (``mission_control_page.dart``:
# ``phase=${fault.phase ?? 'none'}``). That is precisely why the vocabulary is
# closed HERE: a value the enum does not document would decode without
# complaint and print a word nobody can grep the client for.
#
# Only the two placement arms ever spelled a phase, so every mint-phase refusal
# logged ``phase=none`` and the whole point of the field — telling the operator
# whether the roster row or the desk was the half that failed — was carried by
# exactly the arms where the answer was already obvious from ``rolled_back``.
#
# ``null`` is a value, not an omission, and the arms that carry no phase below
# carry none DELIBERATELY: ``workspace_not_found`` and the reservation faults
# are refused before either half is attempted, so naming one of them would be a
# third false claim in a payload this lane is here to make honest.
PHASE_INSTANCE = "instance"
PHASE_PLACEMENT = "placement"
#: The THIRD phase, added by plan S4. It is the one phase whose refusals leave
#: durable state behind ON PURPOSE (D4): the agent is placed, messageable and
#: correct, and only its skill assignment is missing. Every arm below therefore
#: stamps ``rolled_back: false`` — not as a hedge, but as the literal truth,
#: with ``next_expected`` naming the same-key retry that resumes it.
PHASE_SKILLS = "skills"

# ── ``data.rolled_back`` for the reservation faults, one code at a time ───────
#
# :class:`AgentCreateReservationError` is raised by ``reserve_agent_create``
# BEFORE ``perform_agent_create`` writes anything, so it is tempting to answer
# every code with "nothing survives". Two of the three codes make that a lie
# about the world rather than about this attempt, and the launcher's sentence is
# about the world: ``rolled_back: true`` prints "the placement was refused and
# nothing was written."
#
# ``idempotency_conflict``
#     The receipt on disk was READ and validated against this request, and it
#     names a DIFFERENT persona or workspace — so it is another gesture's, and
#     nothing belonging to this one exists. Inventoried: zero paths change.
#     ``True``.
# ``create_lock_unavailable``
#     Another process holds this key's file lock and is mid-sequence. This
#     attempt wrote nothing, but the holder may be between its mint and its
#     placement right now, and we cannot read its receipt — that is what "lock
#     unavailable" means. ``False`` is not a claim that something survived; it
#     is a refusal to claim that nothing did, which is the direction the
#     launcher's parser already calls "the safe direction".
# ``reservation_corrupt``
#     The receipt file EXISTS and will not decode. Its state is unknown and by
#     construction unknowable, so it may name a minted roster row. ``False`` —
#     and this is the one arm on the whole method where "Check the runtime" is
#     the literally correct instruction.
#
# A code missing from this table is answered with NO ``rolled_back`` key, which
# the launcher reads as ``false``. That is deliberate: a new fault whose
# inventory nobody has established must not inherit an optimistic default.
_RESERVATION_ROLLED_BACK: dict[str, bool] = {
    "idempotency_conflict": True,
    "create_lock_unavailable": False,
    "reservation_corrupt": False,
}


@dataclass(frozen=True)
class AgentCreateRefusal:
    """One refused create, in the vocabulary the RPC lane answers in.

    ``code`` is the JSON-RPC error code, ``message`` the operator prose, and
    ``data`` the machine-readable block whose ``reason`` the launcher's
    ``missionAgentCreateReasonFrom`` decoder switches on. Every string here is
    byte-identical to what the handler returned before the hoist.
    """

    code: int
    message: str
    data: dict[str, Any]


@dataclass(frozen=True)
class AgentCreateOutcome:
    """Exactly one of ``result`` / ``refusal`` is set."""

    result: dict[str, Any] | None = None
    refusal: AgentCreateRefusal | None = None


def _refused(code: int, message: Any, data: dict[str, Any]) -> AgentCreateOutcome:
    return AgentCreateOutcome(
        refusal=AgentCreateRefusal(code=code, message=str(message), data=data)
    )


def roster_unavailable_outcome(cause: Any = None) -> AgentCreateOutcome:
    """The roster fault as a REFUSAL, for a lane that met it before the service.

    RD-H6 item 2. A roster fault answered the two create lanes differently:
    ``runtime.agent.create`` refused typed ``persona_roster_unavailable``
    (:func:`normalize_agent_create`'s arm, reached because the RPC lane passes
    no pre-resolved persona), while ``harness agent create`` read the roster
    ITSELF first — ``_persona_by_id`` -> ``ensure_persisted_personas``, the same
    call :func:`persona_roster` wraps, but unwrapped — so a config that process
    could not read tracebacked out of the CLI. One fault, two renderings, and
    the argv one was a stack trace.

    This is the shape the CLI needs and the service cannot give it: the fault
    happens BEFORE ``perform_agent_create`` is entered, so there is no outcome
    to carry it. Returning the outcome (rather than letting the CLI hand-roll an
    envelope) is what keeps the code — and therefore the exit code, via
    ``_AGENT_CREATE_EXIT_CODES`` — from being re-guessed at the call site.

    ``ERR_INVALID_PARAMS`` matches the service's arm exactly: the roster fault
    arrives there through :class:`AgentCreateInvalid`, which the generic
    normaliser arm answers with that code. The two constructions are compared
    for EQUALITY by test rather than trusted to agree — see
    ``tests/hermes_cli/test_agent_create_verb.py``'s parity witness, which
    drives a corrupt-roster fixture down both lanes and asserts the reason and
    the message match.
    """

    return _refused(
        ERR_INVALID_PARAMS,
        persona_roster_unavailable_message(cause),
        # Carries the same stamp as the service's own arm, and must: the whole
        # point of this constructor is that the two lanes render ONE refusal,
        # and a ``data`` block that differed by a key would put the parity
        # witness in ``tests/hermes_cli/test_agent_create_verb.py`` back to
        # comparing two blocks that agree on the fields it happens to check.
        # The fault is met BEFORE ``perform_agent_create`` is entered, so
        # "nothing was written" is if anything more literally true here.
        {"reason": PERSONA_ROSTER_UNAVAILABLE_REASON, "rolled_back": True},
    )


# ── the skills phase (plan S4 / D5) ──────────────────────────────────────────


class AgentCreateSkillsRefused(Exception):
    """A skills-phase refusal, raised where it is decided and rendered once.

    Carries only the arm-specific block; the fields every skills refusal shares
    — ``phase``, ``rolled_back``, ``persona_instance_id``, ``next_expected`` —
    are stamped at the ONE rendering site in :func:`perform_agent_create`, so a
    new arm cannot ship without them.
    """

    def __init__(self, code: int, message: str, data: dict[str, Any]):
        super().__init__(message)
        self.code = code
        self.data = dict(data)


#: What every skills refusal tells the operator to do. It names the SAME key on
#: purpose: the reservation is at ``placed``, so a same-key retry re-enters at
#: the skills phase alone and neither re-mints the roster row nor re-writes the
#: actor. A NEW key would mint a SECOND agent beside the one already standing.
_SKILLS_RETRY_SENTENCE = (
    "the agent is placed and was kept; fix the named skill and retry with the "
    "SAME idempotency_key to resume the skills phase alone"
)


def _skills_refusal(
    exc: AgentCreateSkillsRefused, *, instance_id: str
) -> AgentCreateOutcome:
    """The ONE rendering site for a skills-phase refusal.

    ``persona_instance_id`` is carried because an operator whose skill id was
    wrong needs the id of the agent that IS standing — to message it, to retire
    it, or to name it in the retry. **Cross-repo note for S7:** the launcher
    reads that key off any refusal with ``rolled_back != true`` and publishes it
    as ``orphanInstanceId`` (``mission_agent_create_rpc.dart``). A skills-phase
    instance is NOT an orphan — it is a correctly placed agent — so S7 must
    branch on ``phase == "skills"`` there. No live gesture reaches this today
    (the launcher sends no ``skills``), which is why the useful field wins over
    a decoder that is being changed in the same plan.
    """

    return _refused(
        exc.code,
        exc,
        {
            **exc.data,
            "phase": PHASE_SKILLS,
            "rolled_back": False,
            "persona_instance_id": instance_id,
            "next_expected": _SKILLS_RETRY_SENTENCE,
        },
    )
