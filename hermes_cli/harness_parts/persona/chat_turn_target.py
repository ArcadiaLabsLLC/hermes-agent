"""Which persona and instance a mission-chat turn runs as, and whether its relay chain lets it run.

ONE target resolver for a turn, asked by two callers:

- the turn's front door (``chat_turn_message._cmd_mission_chat_message``), which runs the three steps
  below in its own order, with its session handling between them;
- ``agent_chat_send``'s admission (``tools/agent_chat/addressing.py``), through the door's
  :data:`agent_runtime.mission_chat_door.TURN_TARGET_VERB` and :func:`admit_turn_target`, which runs
  the same three steps synchronously in the sender's turn, so a send the turn would refuse is refused
  there, with ``ok: false``, and is never queued.

Row ``RT-FU-A-SEND-TO-AN-UNPLACED-AGENT-GOES-BACK-TO-THE-SENDER-AND-A-REFUSED-SEND-SAYS-OK`` (seen live
2026-11-21, dispatch-c58c34703868): Base's ``agent_chat_send(@personainst_base, wait=false)`` answered
``ok: true, dispatched: true``; the background turn then refused it ``relay_cycle``. The third case of
"accepted, then refused in the background" after ``RT-AGENT-CHAT-SEND-DISPLAY-NAME-ACCEPTED`` and
``RT-AGENT-CHAT-SEND-ACCEPTS-AN-AGENT-WITH-NO-PROFILE``; each of those added one more admission check
beside the handler's. Admission now asks the handler's own resolver instead.

The steps:

1. :func:`resolve_turn_persona` — the canonical persona, the relay chain's depth / cycle / budget
   answer for what the caller named, and the configured persona.
2. :func:`resolve_turn_instance` — the ambiguous-target guard and, for a send that names no session,
   the instance the turn runs as (the caller's pin, the single in-scope placement, else the operator's
   reuse-or-place or an agent's ``no_instance_in_scope`` refusal; never the hidden copy).
3. :func:`bind_turn` — the chain re-keyed onto that instance; a target that lands on an instance
   already speaking on the chain (the sender itself included) is a ``relay_cycle``.

Each returns the handler's own refusal payload, so both callers say the same words.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from agent_runtime.config import load_agent_runtime_config
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    canonical_chat_instance_id,
    safe_assignment_text,
    safe_assignment_token,
)

from .chat_target import (
    _mission_chat_bare_persona_target,
    _mission_chat_target_decision,
    _persona_by_id,
    _resolve_mission_chat_persona_id,
)

__layer__ = "lanes"
__all__ = [
    "TurnPersona",
    "_session_target",
    "admit_turn_target",
    "bind_turn",
    "caller_instance_pin",
    "resolve_turn_instance",
    "resolve_turn_persona",
]

#: The capability id :func:`admit_turn_target`'s payload carries (the turn's is ``mission.chat.message``).
TARGET_CAPABILITY = "mission.chat.target"
_CAPABILITY = "mission.chat.message"
_ANSWER_CALLER = "answer your caller directly; do not relay onward on this chain"


@dataclass(frozen=True)
class TurnPersona:
    """Step 1's answer: who the turn is, and the chain it runs on until its instance is final."""

    normalized_persona: str
    persona: Any
    relay_chain_in: tuple[str, ...]
    turn_relay_chain: tuple[str, ...]
    relay_deadline: float | None


def _rejected(error_kind: str, error: str, **fields) -> dict[str, Any]:
    from agent_runtime.mission_chat_outcome import ExecutionState

    return {
        "ok": False,
        "capability_id": _CAPABILITY,
        "execution_state": ExecutionState.REJECTED,
        "error_kind": error_kind,
        "error": error,
        **fields,
    }


def _session_target(args, persona_instance_id: str | None, normalized_persona: str) -> tuple[str, str | None]:
    """``(session_id, persona_instance_id)`` this send targets, as the caller wrote it — or adopted.

    An operator CHANNEL id handed back as the session (``<persona>::<tail>``,
    the conversation's own thread id) is adopted. A fresh seeded instance has
    no chat, so its channel's tail is its INSTANCE id, and the first send
    before "new chat" arrived as ``profile_base::personainst_profile_base`` and
    was refused ``unknown_chat_session`` (2026-10-02). It names a thread hermes
    minted: a session tail becomes the session; an instance tail becomes the
    instance pin with the session omitted, so resolve-or-mint opens the root.
    A channel of another persona, or one disagreeing with an explicit pin, is
    left as written and refused by the guards downstream. Adopted values are
    written back onto ``args`` so every later reader agrees with the turn.
    """

    from agent_runtime.operator_channels.instances import split_operator_channel_id
    from agent_runtime.persona_assignments import (
        PERSONA_INSTANCE_ID_PREFIX,
        canonical_persona_instance_id,
        personas_equal,
    )

    session_id = safe_assignment_text(getattr(args, "session_id", None), limit=200)
    channel = split_operator_channel_id(session_id)
    if channel is None:
        return session_id, persona_instance_id
    channel_persona, tail = channel
    if not personas_equal(channel_persona, normalized_persona):
        return session_id, persona_instance_id
    if tail.startswith(PERSONA_INSTANCE_ID_PREFIX):
        tail_instance = canonical_persona_instance_id(tail, persona_id=normalized_persona)
        if not tail_instance or (persona_instance_id and persona_instance_id != tail_instance):
            return session_id, persona_instance_id
        args.session_id = None
        args.persona_instance_id = tail_instance
        return "", tail_instance
    args.session_id = tail
    return tail, persona_instance_id


def caller_instance_pin(args, normalized_persona: str) -> str | None:
    """The canonical instance id the caller pinned, recovered from either slot."""
    from agent_runtime.persona_assignments import (
        PERSONA_INSTANCE_ID_PREFIX,
        canonical_persona_instance_id,
    )

    # Canonicalize a caller-supplied instance id at THIS boundary (the same
    # chokepoint open_chat uses), so an instance-shaped target can never mint a
    # variant row.
    #
    # An instance-shaped `--persona` (`personainst_qa_agent_f24601ba`) IS a
    # caller pin, and it arrives in the persona slot constantly (Mission Control
    # payloads, agent @handle targeting, legacy SessionDB rows).
    # `_resolve_mission_chat_persona_id` canonicalizes it DOWN to the persona id
    # so every persona-keyed lookup works — and the instance half used to be
    # dropped, leaving the caller's explicit pin to be re-decided by the
    # bare-persona placement resolver. Recover the pin at this same chokepoint
    # (no second resolver: `canonical_persona_instance_id` remains the one
    # derivation authority) so an explicit @handle is authoritative BEFORE
    # "placements shadow canonical" runs — which is what that ruling already
    # documents: it never fires when the caller already disambiguated with a
    # `personainst_*` target.
    requested_instance_id = getattr(args, "persona_instance_id", None)
    if not safe_assignment_token(requested_instance_id):
        raw_persona_target = safe_assignment_token(getattr(args, "persona_id", None))
        if raw_persona_target.startswith(PERSONA_INSTANCE_ID_PREFIX):
            requested_instance_id = raw_persona_target
    return canonical_persona_instance_id(requested_instance_id, persona_id=normalized_persona)


def resolve_turn_persona(args, cfg) -> tuple[TurnPersona | None, dict[str, Any] | None]:
    """Step 1: ``(TurnPersona, None)``, or ``(None, the handler's refusal payload)``."""
    from agent_runtime import relay_policy
    from agent_runtime.mission_chat_outcome import ChatErrorKind

    try:
        normalized_persona = _resolve_mission_chat_persona_id(
            args.persona_id, getattr(args, "persona_instance_id", None)
        )
    except ValueError as exc:
        return None, _rejected(
            ChatErrorKind.UNSUPPORTED_PERSONA, safe_assignment_text(str(exc), limit=240),
            persona_id=safe_assignment_token(args.persona_id),
            next_expected="pass a configured persona id, profile_<name>, or a known personainst_* instance id",
        )
    # Relay-chain guard at the canonical persona chokepoint. The chain is
    # explicit envelope provenance (relay_chain / relay_deadline_epoch), so
    # every transport into this handler gets the same depth/cycle/budget
    # answer.
    relay_chain_in = relay_policy.normalize_chain(getattr(args, "relay_chain", None))
    relay_deadline = relay_policy.parse_deadline_epoch(getattr(args, "relay_deadline_epoch", None))
    # Keyed on the INSTANCE the caller named when it named one: two instances of
    # one profile are two speakers (RT-RELAY-CYCLE-SAME-PROFILE-INSTANCES).
    relay_decision = relay_policy.evaluate_relay(
        chain=relay_chain_in,
        target_persona_id=normalized_persona,
        target_instance_id=caller_instance_pin(args, normalized_persona),
        deadline_epoch=relay_deadline,
    )
    if not relay_decision.allowed:
        return None, _rejected(
            relay_decision.error_kind, safe_assignment_text(relay_decision.reason, limit=400),
            persona_id=normalized_persona, relay_chain=list(relay_decision.chain),
            next_expected=_ANSWER_CALLER,
        )
    persona = _persona_by_id(cfg, normalized_persona)
    if persona is None:
        return None, _rejected(
            ChatErrorKind.UNSUPPORTED_PERSONA, f"unknown persona {safe_assignment_token(args.persona_id)}",
            persona_id=safe_assignment_token(args.persona_id),
            next_expected="persist the persona, use profile_<name>, or address a known personainst_* instance",
        )
    # Chain for THIS turn: envelope chain + the persona now speaking.
    return TurnPersona(normalized_persona, persona, relay_chain_in, relay_decision.chain, relay_deadline), None


def resolve_turn_instance(
    *,
    instance_store,
    normalized_persona: str,
    raw_persona_id,
    persona_instance_id: str | None,
    session_id: str | None,
    relay_chain,
    requested_by_session: str | None,
    instance_read_epoch=None,
    relay_chain_in=(),
    place: bool = False,
) -> tuple[str | None, dict[str, Any] | None]:
    """Step 2: ``(instance, None)`` or ``(None, the handler's refusal)``.

    For a send that names no session, *instance* is the instance the turn runs as: the caller's pin,
    else the single in-scope placement ("placements shadow canonical"). With none
    (RT-A-SEND-TO-AN-AGENT-WITH-NO-INSTANCE-IN-REACH-IS-PLACED-OR-REFUSED), never the hidden copy:

    - an AGENT's send (it names its own chat root, or arrives on a relay chain) is refused
      ``no_instance_in_scope``, naming ``agent_add_instance``; an agent's send never places;
    - the OPERATOR's own send runs hermes's one "reuse idle, else place in the Default workspace"
      rule (``agent_create.staff.reuse_or_place``). ``place=False`` is the read-only admission:
      it answers an idle instance, or ``None`` for "the turn places one".

    A ``profile_<name>`` target keeps its profile channel (documented edge, not worked: a profile
    persona is not placeable through ``runtime.agent.place``).
    For a send that names a session, *instance* is the pin (or ``None``): the session's owner decides.
    """

    # Ambiguous-target guard at the canonical persona chokepoint (sibling of the
    # relay-chain guard; same envelope, evaluated for every transport so an
    # instance-id target cannot dodge it). A BARE persona id names a persona, not
    # an instance; when the persona runs more than one live instance and the
    # caller pinned none, the omitted-session default would silently thread onto
    # the canonical primary and DROP the message for every sibling (live
    # 2026-07-19). Refuse with the candidate @handles so the caller can retry
    # against an exact instance.
    target_decision = _mission_chat_target_decision(
        instance_store=instance_store,
        normalized_persona=normalized_persona,
        raw_persona_id=raw_persona_id,
        persona_instance_id=persona_instance_id,
        session_id=session_id,
        relay_chain=relay_chain,
        requested_by_session=requested_by_session,
        instance_read_epoch=instance_read_epoch,
    )
    if not target_decision.allowed:
        return None, _rejected(
            target_decision.error_kind, safe_assignment_text(target_decision.reason, limit=400),
            persona_id=normalized_persona, relay_chain=list(target_decision.chain),
            candidates=[candidate.as_dict() for candidate in target_decision.candidates],
            next_expected="re-send to a specific instance by the @personainst_ handle listed in candidates",
        )
    if session_id:
        return persona_instance_id, None
    # The omitted-session target: ONE instance identity for the turn (the instance
    # the root/mint resolves to is the one `open_chat` binds).
    resolved = persona_instance_id or _mission_chat_bare_persona_target(
        instance_store,
        normalized_persona=normalized_persona,
        requested_by_session=requested_by_session,
    )
    if resolved:
        return resolved, None
    if normalized_persona.startswith("profile_"):
        return canonical_chat_instance_id(normalized_persona, None), None
    if requested_by_session or tuple(relay_chain_in or ()):
        # MUTATION: answer the hidden copy here and test_an_agents_send_to_an_unplaced_persona_is_refused reddens.
        from agent_runtime.target_policy import NO_INSTANCE_IN_SCOPE

        return None, _rejected(
            NO_INSTANCE_IN_SCOPE,
            f"'{normalized_persona}' has no instance in your workspace, so there is no one to send to. "
            "Add one with agent_add_instance, or address an agent that is placed here.",
            persona_id=normalized_persona, relay_chain=list(relay_chain or ()),
            next_expected="call agent_add_instance for this agent, then send to the instance it returns",
        )
    from agent_runtime.agent_create.staff import reuse_or_place

    # MUTATION: answer the hidden copy here and test_an_operator_bare_send_places_in_the_default_workspace reddens.
    instance_id, refusal = reuse_or_place(normalized_persona, place=place)
    if refusal is not None:
        from agent_runtime.target_policy import NO_INSTANCE_IN_SCOPE

        return None, _rejected(
            NO_INSTANCE_IN_SCOPE, safe_assignment_text(refusal.get("message"), limit=400),
            persona_id=normalized_persona, place_refused=refusal.get("reason"),
            next_expected="place the agent in a workspace (runtime.agent.place), then send to it",
        )
    return instance_id, None


def bind_turn(
    *, relay_chain_in, turn_relay_chain, persona_instance_id, normalized_persona: str,
) -> tuple[tuple[str, ...], dict[str, Any] | None]:
    """Step 3: the turn's chain re-keyed onto its final instance, or the ``relay_cycle`` refusal."""
    from agent_runtime import relay_policy

    # The turn's instance is final here: its chain entry becomes that instance, and
    # a bare target that resolved onto an instance already on the chain is a cycle.
    relay_decision = relay_policy.bind_turn_instance(
        chain_in=relay_chain_in, turn_chain=turn_relay_chain, instance_id=persona_instance_id)
    if not relay_decision.allowed:
        return relay_decision.chain, _rejected(
            relay_decision.error_kind, safe_assignment_text(relay_decision.reason, limit=400),
            persona_id=normalized_persona, persona_instance_id=persona_instance_id,
            relay_chain=list(relay_decision.chain), next_expected=_ANSWER_CALLER,
        )
    return relay_decision.chain, None


def admit_turn_target(args) -> dict[str, Any]:
    """The three steps, read-only, for a send not yet made: the handler's refusal payload, or
    ``{"ok": True, "persona_instance_id": …}`` naming the instance the turn would run as.

    *args* carries the turn's own fields (``persona_id``, ``persona_instance_id``, ``session_id``,
    ``clarify_token``, ``requested_by_session``, ``relay_chain``); it is never written. A send that
    names a session (or a clarify token) is bound on its pin when it has one; without a pin the
    session's owner decides, in the turn (a chained hop's authority stays the handler's).
    """
    from .chat_request import _mission_chat_retired_target_refusal, _resolve_mission_chat_clarify_binding

    probe = SimpleNamespace(**vars(args))
    cfg = load_agent_runtime_config()
    target, refusal = resolve_turn_persona(probe, cfg)
    if refusal is not None:
        return refusal
    store = PersonaInstanceStore()
    pin = caller_instance_pin(probe, target.normalized_persona)
    session_id, pin = _session_target(probe, pin, target.normalized_persona)
    binding = _resolve_mission_chat_clarify_binding(probe, session_id=session_id)
    if (binding or {}).get("bound_via") == "clarify_token":
        session_id = safe_assignment_text(binding.get("bound_session_id"), limit=240) or session_id
    requested_by_session = safe_assignment_text(getattr(probe, "requested_by_session", None), limit=200)
    instance, refusal = resolve_turn_instance(
        instance_store=store, normalized_persona=target.normalized_persona,
        raw_persona_id=getattr(probe, "persona_id", None), persona_instance_id=pin,
        session_id=session_id, relay_chain=target.turn_relay_chain,
        requested_by_session=requested_by_session, relay_chain_in=target.relay_chain_in,
    )
    if refusal is not None:
        return refusal
    if not session_id and instance:
        refusal = _mission_chat_retired_target_refusal(
            store, persona_id=target.normalized_persona, persona_instance_id=instance)
        if refusal is not None:
            return refusal
    chain = target.turn_relay_chain
    if instance:
        chain, refusal = bind_turn(
            relay_chain_in=target.relay_chain_in, turn_relay_chain=target.turn_relay_chain,
            persona_instance_id=instance, normalized_persona=target.normalized_persona,
        )
        if refusal is not None:
            return refusal
    return {
        "ok": True,
        "capability_id": TARGET_CAPABILITY,
        "persona_id": target.normalized_persona,
        "persona_instance_id": instance,
        "relay_chain": list(chain),
    }


def _cmd_mission_chat_target(args) -> int:
    """The door's verb: :func:`admit_turn_target`'s payload through ``args.payload_sink``."""
    payload = admit_turn_target(args)
    args.payload_sink(payload)
    return 0 if payload.get("ok") else 2
