"""``agent_chat_send``'s local target, checked BEFORE the send is accepted.

RT-AGENT-CHAT-SEND-DISPLAY-NAME-ACCEPTED (found live 2026-11-06, Eternia w1106b-live-a):
``agent_chat_send {persona_id: "QA Agent A"}`` — a DISPLAY NAME — passed the syntactic persona check
(``resolve_mission_chat_persona_id`` tokenizes it to ``QA_Agent_A``), was dispatched, and only the
background delivery refused ``unknown persona QA_Agent_A``, after the sender had been told it was sent.

:func:`resolve_send_target` answers synchronously, from the same sender-scoped addressable roster
``agent_chat_threads`` lists:

- a ``personainst_*`` handle passes as given — unless it is profile-backed (a stored instance, or a
  ``personainst_profile_<name>`` channel) and its profile is gone (:func:`agent_runtime.roster_reach.profile_missing`,
  the rule that already hides such an agent from the roster): then it is refused ``unsupported_persona``
  listing the addressable handles (RT-AGENT-CHAT-SEND-ACCEPTS-AN-AGENT-WITH-NO-PROFILE, seen live
  2026-11-15: Base's send to the invented ``personainst_profile_charsheet`` answered ``dispatched: true``
  and failed in the background "Hermes profile 'charsheet' does not exist");
- an id naming a configured persona passes as given;
- otherwise a display name naming exactly ONE addressable instance (case and spacing ignored) is
  rewritten to that instance's handle;
- two or more → refused ``ambiguous_target`` (the word and candidate shape
  :mod:`agent_runtime.target_policy` owns) with the candidates' handles;
- none → refused ``unsupported_persona`` listing the addressable handles — except an id-shaped target
  when NO teammate is addressable (a bare home has no roster to judge it by; the handler decides).
"""

from __future__ import annotations

from types import SimpleNamespace

from .lane import _looks_like_instance_handle, refusal_json

__layer__ = "lanes"
__all__ = ["resolve_send_target"]

#: How many addressable handles a refusal lists (a roster is small; the bound keeps a reply short).
_LISTED = 20


def _folded(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def _addressable(requested_by_session):
    from agent_runtime import workspace_scope
    from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
    from agent_runtime.persona_assignments import (
        PersonaInstanceStore, is_canonical_persona_channel, sender_scope_workspace_id,
    )

    cfg = load_agent_runtime_config()  # the CLI lane's own read (``chat_turn_message``): one answer
    personas = list(ensure_persisted_personas(cfg))
    store = PersonaInstanceStore()
    store.ensure_for_personas(personas)
    roster = workspace_scope.addressable_roster(
        store.list_all(),
        scope_workspace_id=sender_scope_workspace_id(requested_by_session, instance_store=store),
        is_canonical=is_canonical_persona_channel,
    )
    return cfg, personas, [instance for instance in roster if getattr(instance, "id", None)]


def resolve_send_target(persona_id: str, *, requested_by_session=None) -> tuple[str, str | None]:
    """``(target, None)`` — the id to send to — or ``(persona_id, refusal_json)``."""

    if _looks_like_instance_handle(persona_id):
        # Judged on its own facts (the store and the profiles folder), never deferred for an empty
        # roster: a namespace whose only agent is the sender has no teammates to list, and that is
        # exactly where an invented handle was accepted live (2026-11-15, w1115e-h4). The roster is
        # read only to word a refusal: reading it mints the scope's canonical rows, which a send to a
        # reachable handle never did.
        why = _unreachable_handle(persona_id)
        if why is None:
            return persona_id, None
        return persona_id, _no_teammate(persona_id, _addressable(requested_by_session)[2], why)
    from agent_runtime.persona_assignments import safe_assignment_token
    from hermes_cli.harness_parts.persona.chat_target import _persona_by_id

    cfg, personas, roster = _addressable(requested_by_session)
    if _persona_by_id(cfg, persona_id) is not None:
        return persona_id, None
    wanted = _folded(persona_id)
    names = {getattr(persona, "id", None): _folded(getattr(persona, "display_name", None)) for persona in personas}
    matches = [instance for instance in roster
               if wanted in (_folded(getattr(instance, "display_name", None)), names.get(instance.persona_id))]
    if len(matches) == 1:
        return matches[0].id, None
    if matches:
        from agent_runtime.target_policy import AMBIGUOUS_TARGET, TargetCandidate

        listed = [TargetCandidate(instance.id, getattr(instance, "display_name", None) or instance.id)
                  for instance in matches][:_LISTED]
        return persona_id, refusal_json(
            f"{persona_id!r} names {len(matches)} teammates; send to one of their handles: "
            + ", ".join(candidate.instance_id for candidate in listed) + ".",
            error_kind=AMBIGUOUS_TARGET, target_persona=persona_id,
            candidates=[candidate.as_dict() for candidate in listed],
        )
    if not roster and safe_assignment_token(persona_id) == persona_id:
        # No roster to judge an id-shaped target against (a bare home): the handler's own check decides.
        return persona_id, None
    return persona_id, _no_teammate(persona_id, roster, None)


def _unreachable_handle(handle: str) -> str | None:
    """Why no message can reach the instance *handle* names, or ``None`` when one can.

    The same rule the roster offer uses (``roster_reach.profile_missing``), asked at admission, so a
    send is refused in the turn that made it instead of being accepted and failing in the background.
    """
    from agent_runtime.persona_assignments import PersonaInstanceStore, safe_assignment_token
    from agent_runtime.roster_reach import profile_missing

    # The same token ``_looks_like_instance_handle`` judged: seen live, the model wrote ``@personainst_…``.
    handle = safe_assignment_token(handle)
    try:
        instance = PersonaInstanceStore().get(handle)
    except FileNotFoundError:
        instance = None
    except Exception:  # an unreadable row is the handler's to judge, never a refusal here
        return None
    if instance is not None:
        missing = profile_missing(instance)
        return None if missing is None else f"its Hermes profile {missing!r} does not exist"
    token = handle[len(_PROFILE_CHANNEL):] if handle.startswith(_PROFILE_CHANNEL) else ""
    if token:
        # A profile's canonical channel the store has not minted yet: reachable while the profile exists.
        missing = profile_missing(SimpleNamespace(role="profile", profile_id=token))
        return None if missing is None else f"its Hermes profile {missing!r} does not exist"
    # Any other unstored handle (a placement the handler mints on first use, ``personainst_qa_agent_2``)
    # is the handler's to judge: it derives the persona from the handle and refuses an unknown one.
    return None


#: The canonical channel id of a ``profile_<name>`` persona (``persona_instance_id_for``).
_PROFILE_CHANNEL = "personainst_profile_"


def _no_teammate(persona_id: str, roster, why: str | None) -> str:
    listed = [{"handle": instance.id, "display_name": getattr(instance, "display_name", None) or instance.id}
              for instance in roster][:_LISTED]
    reason = f" ({why})" if why else ""
    return refusal_json(
        f"no teammate is addressed as {persona_id!r}{reason}; send to a persona id or one of these handles: "
        + (", ".join(f"{row['handle']} ({row['display_name']})" for row in listed) or "none are addressable"),
        error_kind="unsupported_persona", target_persona=persona_id, addressable=listed,
    )
