"""``agent_chat_send``'s local target, checked BEFORE the send is accepted.

RT-AGENT-CHAT-SEND-DISPLAY-NAME-ACCEPTED (found live 2026-11-06, Eternia w1106b-live-a):
``agent_chat_send {persona_id: "QA Agent A"}`` — a DISPLAY NAME — passed the syntactic persona check
(``resolve_mission_chat_persona_id`` tokenizes it to ``QA_Agent_A``), was dispatched, and only the
background delivery refused ``unknown persona QA_Agent_A``, after the sender had been told it was sent.

:func:`resolve_send_target` answers synchronously, from the same sender-scoped addressable roster
``agent_chat_threads`` lists:

- a ``personainst_*`` handle, or an id naming a configured persona, passes as given;
- otherwise a display name naming exactly ONE addressable instance (case and spacing ignored) is
  rewritten to that instance's handle;
- two or more → refused ``ambiguous_persona`` with the candidates' handles;
- none → refused ``unsupported_persona`` listing the addressable handles — except an id-shaped target
  when NO teammate is addressable (a bare home has no roster to judge it by; the handler decides).
"""

from __future__ import annotations

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
        return persona_id, None
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
        handles = [instance.id for instance in matches][:_LISTED]
        return persona_id, refusal_json(
            f"{persona_id!r} names {len(matches)} teammates; send to one of their handles: {', '.join(handles)}.",
            error_kind="ambiguous_persona", target_persona=persona_id, candidates=handles,
        )
    if not roster and safe_assignment_token(persona_id) == persona_id:
        # No roster to judge an id-shaped target against (a bare home): the handler's own check decides.
        return persona_id, None
    listed = [{"handle": instance.id, "display_name": getattr(instance, "display_name", None) or instance.id}
              for instance in roster][:_LISTED]
    return persona_id, refusal_json(
        f"no teammate is addressed as {persona_id!r}; send to a persona id or one of these handles: "
        + (", ".join(f"{row['handle']} ({row['display_name']})" for row in listed) or "none are addressable"),
        error_kind="unsupported_persona", target_persona=persona_id, addressable=listed,
    )
