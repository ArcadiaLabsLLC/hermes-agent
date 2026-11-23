"""Which instance a channel is: channel keys, the canonical instance, recency, the merged trace, and the ancestry graph."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Iterable

from ..clock import parse_iso
from ..models import PersonaInstance
from ..persona_chat_history.vocabulary import canonical_chat_persona_id
from ..serde import safe_assignment_text, safe_assignment_token

from .vocabulary import (
    _CHAT_INSTANCE_MODES,
    first_present_text,
    _safe_instance_id,
    _safe_session,
)

if TYPE_CHECKING:  # the builder imports this module; annotation only
    from .summary import _OperatorChannelBuilder

__layer__ = "policy"


#: Joins the two halves of :attr:`ChannelIdentity.channel_id`.
CHANNEL_ID_SEPARATOR = "::"


def split_operator_channel_id(value: Any) -> tuple[str, str] | None:
    """``(persona_id, tail)`` of an operator channel id, or ``None`` for anything else.

    The inverse of :attr:`ChannelIdentity.channel_id`: ``tail`` is the channel's
    chat session id, or — for an instance with no chat yet — its canonical
    instance id. A chat session id never contains the separator, so a value that
    does is a channel id handed back where a session id was expected (a fresh
    seeded instance's first send, 2026-10-02), never a session.
    """

    text = safe_assignment_text(value, limit=400)
    if not text or CHANNEL_ID_SEPARATOR not in text:
        return None
    persona_id, _, tail = text.partition(CHANNEL_ID_SEPARATOR)
    if not persona_id or not tail or CHANNEL_ID_SEPARATOR in tail:
        return None
    return persona_id, tail


@dataclass(frozen=True)
class ChannelIdentity:
    """Who one operator channel is: the rows it projects and the ids derived from them.

    ONE derivation, read by the channel build and by the ancestry graph — the
    two spelled it separately, field for field, before lane B3.
    """

    history: dict[str, Any] | None
    trace: dict[str, Any] | None
    canonical: PersonaInstance | None
    persona_id: str
    canonical_id: str
    session_id: str | None

    @property
    def channel_id(self) -> str:
        return f"{self.persona_id}{CHANNEL_ID_SEPARATOR}{self.session_id or self.canonical_id}"

    @property
    def is_empty(self) -> bool:
        return self.canonical is None and self.history is None and self.trace is None

    def _canonical_attr(self, name: str) -> Any:
        return getattr(self.canonical, name, None) if self.canonical is not None else None

    @property
    def goal_id(self) -> str | None:
        return first_present_text(
            self._canonical_attr("goal_id"),
            self.history.get("goal_id") if self.history else None,
        )


def channel_identity(builder: Any) -> ChannelIdentity:
    """The :class:`ChannelIdentity` of one ``_OperatorChannelBuilder``."""

    history = builder._bound_history() or _latest_history(builder.history_rows)
    trace = _merged_trace(builder.trace_rows)
    canonical = _canonical_instance(builder.instances, history=history)
    attr = (lambda name: getattr(canonical, name, None)) if canonical is not None else (lambda name: None)
    persona_id = first_present_text(
        attr("persona_id"),
        history.get("persona_id") if history else None,
        trace.get("persona_id") if trace else None,
    )
    persona_id = canonical_chat_persona_id(persona_id) or persona_id or "unknown"
    # No fallback to ``persona_instance_id_for(persona_id)``: a channel nothing names an instance for is
    # not filed under an agent's hidden copy (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT); its
    # history row keeps the ``history_without_instance`` warning.
    # MUTATION: restore the fallback and test_a_channel_naming_no_instance_is_not_filed_under_a_hidden_copy reddens.
    canonical_id = first_present_text(
        attr("id"),
        history.get("persona_instance_id") if history else None,
        trace.get("persona_instance_id") if trace else None,
    )
    session_id = first_present_text(
        history.get("session_id") if history else None,
        trace.get("session_id") if trace else None,
        attr("session_id"),
    )
    return ChannelIdentity(history, trace, canonical, persona_id, canonical_id or "", session_id)


def is_newborn_channel(identity: ChannelIdentity, messages: list[Any]) -> bool:
    """A freshly-created chat into which nothing has flowed yet.

    It has a session id, but no curated history row, no trace, no task binding,
    and zero projected conversation messages (operator rows included). A newborn
    is neither a projection loss nor an empty-trace anomaly; both warnings stay
    silent until real content arrives (live 2026-07-18: creating a fresh
    neko_supervisor chat surfaced two false-positive contract warnings).
    """

    return (
        bool(identity.session_id)
        and identity.history is None
        and identity.trace is None
        and not messages
    )


def _operator_conversation_relationships(
    builders: Iterable[_OperatorChannelBuilder],
) -> dict[str, tuple[str, str | None]]:
    """Resolve conversation ancestry from the persisted instance graph.

    ``PersonaInstance.steered_by`` is the authority.  The conversation wire has
    one parent field, so it follows the store's primary-parent convention (the
    first entry, mirrored by ``spawned_by``).  A missing/out-of-roster parent or
    a cycle degrades to a standalone thread; no persona id is promoted to root
    by convention.
    """

    instances_by_id: dict[str, PersonaInstance] = {}
    channel_by_instance_id: dict[str, str] = {}
    #: The wire's canonical id -> the instance id the walk starts from.
    canonical_ids: dict[str, str] = {}
    for builder in builders:
        identity = channel_identity(builder)
        if identity.canonical is None:
            continue
        canonical_id = _safe_instance_id(identity.canonical)
        if canonical_id:
            canonical_ids[identity.canonical_id] = canonical_id
        for instance in builder.instances:
            instance_id = _safe_instance_id(instance)
            if not instance_id:
                continue
            instances_by_id[instance_id] = instance
            channel_by_instance_id[instance_id] = identity.channel_id

    def _parents_of(instance_id: str) -> list[Any] | None:
        instance = instances_by_id.get(instance_id)
        return None if instance is None else list(getattr(instance, "steered_by", None) or [])

    walked = thread_relationships(canonical_ids.values(), channel_by_instance_id, _parents_of)
    return {key: walked[instance_id] for key, instance_id in canonical_ids.items() if instance_id in walked}


def thread_relationships(
    canonical_ids: Iterable[str],
    channel_by_instance_id: dict[str, str],
    parents_of: Callable[[str], list[Any] | None],
) -> dict[str, tuple[str, str | None]]:
    """``canonical instance id -> (root_thread_id, parent_thread_id)``: the ONE ancestry walk.

    Read by the channel build (over its builders) and by the serve's resident
    core after a steer (over a core's own channels and instance rows,
    :func:`core_thread_relationships`), so a steer folded in place and a full
    build name the same threads. ``parents_of`` answers an instance's
    ``steered_by`` list, or ``None`` for an instance outside the roster.
    """

    def _primary(instance_id: str) -> tuple[bool, str | None]:
        parents = parents_of(instance_id)
        if parents is None:
            return False, None
        ids = [parent_id for raw in parents if (parent_id := safe_assignment_text(raw, limit=160))]
        return True, (ids[0] if ids else None)

    relationships: dict[str, tuple[str, str | None]] = {}
    for instance_id in canonical_ids:
        own_channel_id = channel_by_instance_id.get(instance_id)
        if own_channel_id is None:
            continue
        _known, primary_parent_id = _primary(instance_id)
        parent_thread_id = channel_by_instance_id.get(primary_parent_id or "")
        root_thread_id = own_channel_id
        cursor = primary_parent_id
        seen = {instance_id}
        ancestry_valid = True
        while cursor:
            if cursor in seen:
                ancestry_valid = False
                break
            seen.add(cursor)
            parent_channel_id = channel_by_instance_id.get(cursor)
            known, next_parent = _primary(cursor)
            if parent_channel_id is None or not known:
                ancestry_valid = False
                break
            root_thread_id = parent_channel_id
            cursor = next_parent
        if not ancestry_valid:
            root_thread_id = own_channel_id
            parent_thread_id = None
        relationships[instance_id] = (root_thread_id, parent_thread_id)
    return relationships


def core_thread_relationships(core: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    """``channel_id -> (root_thread_id, parent_thread_id)`` re-derived from a core's
    own ``operator_channels`` (each channel's ``source_instance_ids``) and
    ``persona_instances`` rows (their ``steered_by``), by :func:`thread_relationships`."""

    channels = core.get("operator_channels") if isinstance(core.get("operator_channels"), dict) else {}
    instances = core.get("persona_instances") if isinstance(core.get("persona_instances"), dict) else {}
    channel_by_instance_id: dict[str, str] = {}
    canonical_by_channel: dict[str, str] = {}
    for channel_id, row in channels.items():
        if not isinstance(row, dict):
            continue
        canonical_id = row.get("persona_instance_id")
        if isinstance(canonical_id, str) and canonical_id in instances:
            canonical_by_channel[channel_id] = canonical_id
        for instance_id in row.get("source_instance_ids") or ():
            if isinstance(instance_id, str) and instance_id in instances:
                channel_by_instance_id[instance_id] = channel_id

    def _parents_of(instance_id: str) -> list[Any] | None:
        row = instances.get(instance_id)
        return list(row.get("steered_by") or []) if isinstance(row, dict) else None

    by_instance = thread_relationships(canonical_by_channel.values(), channel_by_instance_id, _parents_of)
    return {
        channel_id: by_instance[instance_id]
        for channel_id, instance_id in canonical_by_channel.items()
        if instance_id in by_instance
    }


def _channel_key_for_instance(instance: PersonaInstance) -> str:
    mode = safe_assignment_token(getattr(instance, "mode", None))
    session_id = _safe_session(getattr(instance, "session_id", None))
    persona_id = canonical_chat_persona_id(getattr(instance, "persona_id", None)) or "unknown"
    if session_id and mode in _CHAT_INSTANCE_MODES:
        return f"session:{session_id}"
    # An instance with no readable id is keyed by its profile's own channel, else its agent's template id:
    # never the hidden copy ``personainst_<persona>`` nothing mints any more.
    fallback = f"personainst_{persona_id}" if persona_id.startswith("profile_") else f"persona:{persona_id}"
    return f"instance:{_safe_instance_id(instance) or fallback}"


def _canonical_instance(
    instances: list[PersonaInstance],
    *,
    history: dict[str, Any] | None,
) -> PersonaInstance | None:
    if not instances:
        return None
    history_instance = safe_assignment_text(
        (history or {}).get("persona_instance_id"), limit=160
    )
    if history_instance:
        for instance in instances:
            if _safe_instance_id(instance) == history_instance:
                return instance
    canonical_profile = [
        instance
        for instance in instances
        if (_safe_instance_id(instance) or "").startswith("personainst_profile_")
    ]
    if canonical_profile:
        return _newest_instance(canonical_profile)
    return _newest_instance(instances)


def _newest_instance(instances: list[PersonaInstance]) -> PersonaInstance:
    return sorted(instances, key=_instance_recency, reverse=True)[0]


def _source_instance_ids_conflict(
    source_instance_ids: list[str],
    *,
    instances: list[PersonaInstance],
    history_rows: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
) -> bool:
    if len(source_instance_ids) <= 1:
        return False
    rows = [
        *history_rows,
        *(row for row in trace_rows if not row.get("_mirrored_to_root")),
    ]
    sessions = {
        session
        for session in [
            *(_safe_session(getattr(instance, "session_id", None)) for instance in instances),
            *(_safe_session(row.get("session_id")) for row in rows),
        ]
        if session
    }
    if len(sessions) > 1:
        return True
    personas = {
        persona
        for persona in [
            *(
                canonical_chat_persona_id(getattr(instance, "persona_id", None))
                for instance in instances
            ),
            *(canonical_chat_persona_id(row.get("persona_id")) for row in rows),
        ]
        if persona
    }
    if len(personas) > 1:
        return True
    if any(item.startswith("personainst_operator_") for item in source_instance_ids):
        return False
    # Reaching here means one persona and at most one session. Within that,
    # id multiplicity contributed ONLY by history/trace row attribution is not
    # a projection collision: a pre-per-instance-session chat row can sit on
    # the persona's canonical session while naming the placement-backed sibling
    # that answered it (live evidence 2026-08-31: the neko_supervisor canonical
    # channel carried a 2026-07-20 history row attributed to
    # personainst_neko_supervisor_agent_47a47348). Nothing mints that shape
    # anymore — sessions are per-instance — so warning on it is a permanent,
    # operator-unactionable false positive (the canonical singleton cannot be
    # retired). Two live instance ROWS folding onto one channel remain the
    # genuine collision.
    instance_ids = {
        instance_id
        for instance_id in (_safe_instance_id(instance) for instance in instances)
        if instance_id
    }
    return len(instance_ids) > 1


def _instance_recency(instance: PersonaInstance) -> tuple[int, str]:
    for value in (
        getattr(instance, "updated_at", None),
        getattr(instance, "last_heartbeat_at", None),
    ):
        parsed = parse_iso(value)
        if parsed is not None:
            return (1, parsed.isoformat())
    return (0, _safe_instance_id(instance) or "")


def _latest_history(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(rows, key=lambda row: _row_recency(row), reverse=True)[0]


def _row_recency(row: dict[str, Any]) -> tuple[int, str]:
    for key in ("updated_at", "created_at"):
        parsed = parse_iso(row.get(key))
        if parsed is not None:
            return (1, parsed.isoformat())
    return (0, str(row.get("session_id") or ""))


def _merged_trace(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    first = next((row for row in rows if not row.get("_mirrored_to_root")), rows[0])
    entries_by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        for entry in list(row.get("entries") or []):
            if not isinstance(entry, dict):
                continue
            entries_by_key[_trace_entry_key(entry)] = entry
    entries = sorted(entries_by_key.values(), key=_trace_entry_sort_key)
    return {
        "persona_instance_id": first.get("persona_instance_id"),
        "persona_id": first.get("persona_id"),
        "session_id": first.get("session_id"),
        "entries": entries,
    }


def _trace_entry_key(entry: dict[str, Any]) -> str:
    return "|".join(
        str(entry.get(key) or "")
        for key in ("ts", "event", "tool_name", "summary", "run_id", "status")
    )


def _trace_entry_sort_key(entry: dict[str, Any]) -> tuple[int, str]:
    parsed = parse_iso(entry.get("ts"))
    if parsed is not None:
        return (1, parsed.isoformat())
    return (0, str(entry.get("ts") or ""))
