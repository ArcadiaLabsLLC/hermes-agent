"""operator_channel_summary and the per-channel builder: the Agent Console's single render contract."""

from __future__ import annotations

from typing import Any, Iterable

from ..models import PersonaInstance
from ..serde import safe_assignment_text, safe_assignment_token

from .conversation import _conversation_contract, _turn_identity_dropped, _turn_identity_mismatched
from .instances import (
    ChannelIdentity,
    _channel_key_for_instance,
    _latest_history,
    _operator_conversation_relationships,
    _source_instance_ids_conflict,
    channel_identity,
    is_dormant_channel,
    is_newborn_channel,
)
from .vocabulary import (
    FLOW_MESSAGE_KINDS,
    OPERATOR_CHANNELS_SCHEMA_VERSION,
    _display_name_from_history,
    _safe_instance_id,
    _safe_session,
    first_present_text,
)

__layer__ = "policy"


def operator_channel_summary(
    *,
    persona_instances: Iterable[PersonaInstance],
    persona_chat_history: list[dict[str, Any]],
    persona_chat_trace: list[dict[str, Any]],
    accountant: Any = None,
    intentionally_omitted_history_session_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Project the Agent Console's single render contract.

    Raw persona instances, curated chat history, and tool trace are useful
    diagnostics, but the Launcher console must not have to join them in widget
    code. This projection owns that join and emits loud warnings when the raw
    sources disagree.

    S47 removed the ``tasks`` parameter and the ``_TaskLookup`` it built. Both
    production callers (``snapshot.build_snapshot`` and ``status.build_status``)
    passed a ``[]`` literal, so the resolved task was permanently ``None`` and
    everything downstream of it — the synthetic goal-input message, the title
    and run-id fallbacks, the ``goal_id`` / ``task_id`` / ``updated_at``
    fallbacks — was unreachable, not optional.
    """

    omitted_history_session_ids = {
        session_id
        for item in (intentionally_omitted_history_session_ids or [])
        if (session_id := _safe_session(item))
    }
    channels: dict[str, _OperatorChannelBuilder] = {}
    by_session: dict[str, _OperatorChannelBuilder] = {}
    by_instance: dict[str, _OperatorChannelBuilder] = {}
    # instance id → display name, built once from the FULL roster so a relayed
    # message can name the sending agent (the sender may be any instance, not
    # just this channel's owner). Threaded down to the history projection as an
    # additive lookup; never re-derived per row.
    display_names: dict[str, str] = {}

    for instance in persona_instances:
        key = _channel_key_for_instance(instance)
        builder = channels.get(key)
        if builder is None:
            builder = _OperatorChannelBuilder(key)
            channels[key] = builder
        builder.add_instance(instance)
        session_id = _safe_session(getattr(instance, "session_id", None))
        instance_id = _safe_instance_id(instance)
        if session_id:
            by_session[session_id] = builder
        if instance_id:
            by_instance[instance_id] = builder
            name = safe_assignment_text(getattr(instance, "display_name", None), limit=120)
            if name:
                display_names[instance_id] = name

    for row in persona_chat_history:
        session_id = _safe_session(row.get("session_id"))
        instance_id = safe_assignment_text(row.get("persona_instance_id"), limit=160)
        builder = by_session.get(session_id or "") or by_instance.get(instance_id or "")
        if builder is None:
            key = f"session:{session_id}" if session_id else f"history:{instance_id or len(channels)}"
            builder = channels.setdefault(key, _OperatorChannelBuilder(key))
            if session_id:
                by_session[session_id] = builder
            builder.warn(
                "history_without_instance",
                "chat history row had no matching persona instance",
                entity_id=session_id or instance_id,
            )
        builder.add_history(row)

    for row in persona_chat_trace:
        session_id = _safe_session(row.get("session_id"))
        instance_id = safe_assignment_text(row.get("persona_instance_id"), limit=160)
        builder = by_session.get(session_id or "") or by_instance.get(instance_id or "")
        if builder is None:
            key = f"session:{session_id}" if session_id else f"trace:{instance_id or len(channels)}"
            builder = channels.setdefault(key, _OperatorChannelBuilder(key))
            if session_id:
                by_session[session_id] = builder
            builder.warn(
                "trace_without_instance",
                "trace row had no matching persona instance",
                entity_id=session_id or instance_id,
            )
        builder.add_trace(row)

    conversation_relationships = _operator_conversation_relationships(channels.values())

    return [
        channel
        for channel in (
            builder.build(
                accountant=accountant,
                display_names=display_names,
                omitted_history_session_ids=omitted_history_session_ids,
                conversation_relationships=conversation_relationships,
            )
            for builder in channels.values()
        )
        if channel is not None
    ]


class _OperatorChannelBuilder:
    def __init__(self, key: str):
        self.key = key
        self.instances: list[PersonaInstance] = []
        self.history_rows: list[dict[str, Any]] = []
        self.trace_rows: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []

    def add_instance(self, instance: PersonaInstance) -> None:
        self.instances.append(instance)

    def add_history(self, row: dict[str, Any]) -> None:
        self.history_rows.append(row)

    def add_trace(self, row: dict[str, Any]) -> None:
        self.trace_rows.append(row)

    def warn(self, code: str, detail: str, *, entity_id: str | None = None) -> None:
        warning: dict[str, Any] = {"code": code, "detail": detail}
        if entity_id:
            warning["entity_id"] = entity_id
        self.warnings.append(warning)

    def _bound_history(self) -> dict[str, Any] | None:
        """History row for an instance's BOUND session, when present.

        ``persona.instance.open_chat`` rebinds an instance to an arbitrary
        saved session; the channel must project that binding, not whichever
        curated row happens to carry the newest timestamp. Observed live
        2026-07-07: rebinding Alice to an older chat left her channel on the
        newest session, so the Launcher console never switched chats.
        """
        bound = {
            session
            for session in (
                _safe_session(getattr(instance, "session_id", None))
                for instance in self.instances
            )
            if session
        }
        if not bound:
            return None
        matches = [
            row
            for row in self.history_rows
            if _safe_session(row.get("session_id")) in bound
        ]
        if not matches:
            return None
        return _latest_history(matches)

    def build(
        self,
        *,
        accountant: Any = None,
        display_names: dict[str, str] | None = None,
        omitted_history_session_ids: set[str] | None = None,
        conversation_relationships: dict[str, tuple[str, str | None]] | None = None,
    ) -> dict[str, Any] | None:
        """``identity -> sources -> conversation -> warnings -> row``."""

        identity = channel_identity(self)
        if identity.is_empty:
            return None
        source_instance_ids = self._source_instance_ids()
        conversation = self._conversation(
            identity,
            accountant=accountant,
            display_names=display_names,
            conversation_relationships=conversation_relationships,
        )
        warnings = self._warnings(
            identity,
            source_instance_ids,
            conversation,
            omitted_history_session_ids=omitted_history_session_ids or set(),
        )
        return self._row(identity, source_instance_ids, conversation, warnings)

    def _source_instance_ids(self) -> list[str]:
        return sorted(
            {
                item
                for item in [
                    *(_safe_instance_id(instance) for instance in self.instances),
                    *(
                        safe_assignment_text(row.get("persona_instance_id"), limit=160)
                        for row in self.history_rows
                    ),
                    *(
                        safe_assignment_text(row.get("persona_instance_id"), limit=160)
                        for row in self.trace_rows
                        if not row.get("_mirrored_to_root")
                    ),
                ]
                if item
            }
        )

    def _conversation(
        self,
        identity: ChannelIdentity,
        *,
        accountant: Any,
        display_names: dict[str, str] | None,
        conversation_relationships: dict[str, tuple[str, str | None]] | None,
    ) -> dict[str, Any]:
        channel_id = identity.channel_id
        root_thread_id, parent_thread_id = (conversation_relationships or {}).get(
            identity.canonical_id,
            (channel_id, None),
        )
        canonical = identity.canonical
        return _conversation_contract(
            channel_id=channel_id,
            persona_id=identity.persona_id,
            persona_instance_id=identity.canonical_id,
            session_id=identity.session_id,
            task_id=identity.task_id,
            goal_id=identity.goal_id,
            title=first_present_text(
                identity.history.get("title") if identity.history else None,
                getattr(canonical, "current_chat_goal", None) if canonical is not None else None,
                "Mission run",
            )
            or "Mission run",
            state=safe_assignment_token(getattr(canonical, "state", None)) if canonical is not None else "unknown",
            history=identity.history,
            trace=identity.trace,
            accountant=accountant,
            display_names=display_names,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
        )

    def _warnings(
        self,
        identity: ChannelIdentity,
        source_instance_ids: list[str],
        conversation: dict[str, Any],
        *,
        omitted_history_session_ids: set[str],
    ) -> list[dict[str, Any]]:
        warnings = list(self.warnings)
        if _source_instance_ids_conflict(
            source_instance_ids,
            instances=self.instances,
            history_rows=self.history_rows,
            trace_rows=self.trace_rows,
        ):
            warnings.append(
                {
                    "code": "duplicate_instances_same_channel",
                    "detail": "multiple persona instances projected to one operator channel",
                    "entity_ids": source_instance_ids,
                }
            )
        messages = conversation.get("messages") or []
        entries = list(identity.trace.get("entries") or []) if identity.trace else []
        if _turn_identity_dropped(entries, messages):
            warnings.append(
                {
                    "code": "operator_conversations.turn_identity_dropped",
                    "detail": "trace entries carry turn_id but projected tool/thinking conversation rows dropped it",
                    "entity_id": identity.channel_id,
                }
            )
        if _turn_identity_mismatched(messages):
            warnings.append(
                {
                    "code": "operator_conversations.turn_identity_mismatched",
                    "detail": "a projected terminal reply turn_id disagrees with its typed assistant client_message_id",
                    "entity_id": identity.channel_id,
                }
            )
        warnings.extend(_emptiness_warnings(identity, messages, omitted_history_session_ids))
        return warnings

    def _row(
        self,
        identity: ChannelIdentity,
        source_instance_ids: list[str],
        conversation: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        canonical, history = identity.canonical, identity.history
        entries = list(identity.trace.get("entries") or []) if identity.trace else []
        return {
            "schema_version": OPERATOR_CHANNELS_SCHEMA_VERSION,
            "channel_id": identity.channel_id,
            "persona_id": identity.persona_id,
            "persona_instance_id": identity.canonical_id,
            "session_id": identity.session_id,
            "task_id": identity.task_id,
            "goal_id": identity.goal_id,
            "display_name": first_present_text(
                getattr(canonical, "display_name", None) if canonical is not None else None,
                _display_name_from_history(history),
                identity.persona_id,
            ),
            "state": safe_assignment_token(getattr(canonical, "state", None)) if canonical is not None else "unknown",
            "mode": safe_assignment_token(getattr(canonical, "mode", None)) if canonical is not None else None,
            "source_instance_ids": source_instance_ids,
            "history": history,
            "trace": identity.trace,
            "conversation": conversation,
            "conversation_status": conversation.get("status"),
            "message_count": int(history.get("message_count") or len(history.get("messages") or [])) if history else 0,
            "trace_count": len(entries),
            "tool_trace_count": len([entry for entry in entries if entry.get("tool_name")]),
            "warnings": warnings,
        }


def _emptiness_warnings(
    identity: ChannelIdentity, messages: list[Any], omitted_history_session_ids: set[str]
) -> list[dict[str, Any]]:
    """``session_without_history`` and ``trace_empty``, evaluated AFTER the conversation.

    A channel whose goal turns already flow as canonical messages is not an
    empty channel, even when the legacy trace lane happens to be null; a
    newborn and a dormant channel (:func:`instances.is_newborn_channel`,
    :func:`instances.is_dormant_channel`) raise neither warning.
    """

    newborn = is_newborn_channel(identity, messages)
    warnings: list[dict[str, Any]] = []
    # session_without_history is the genuine projection-loss signal: real
    # content flowed (conversation messages or a trace) but no curated history
    # row backs it. A newborn — nothing has flowed yet — stays silent.
    if (
        identity.history is None
        and identity.session_id
        and not newborn
        and identity.session_id not in omitted_history_session_ids
    ):
        warnings.append(
            {
                "code": "session_without_history",
                "detail": "operator channel has a session id but no curated chat history row",
                "entity_id": identity.session_id,
            }
        )
    has_flow_messages = any(message.get("kind") in FLOW_MESSAGE_KINDS for message in messages)
    if (
        identity.trace is None
        and not has_flow_messages
        and (identity.history is None or identity.task_id)
        and not is_dormant_channel(identity, messages)
        and not newborn
    ):
        warnings.append(
            {
                "code": "trace_empty",
                "detail": "operator channel has no tool/progress trace rows",
            }
        )
    return warnings
