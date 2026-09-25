"""The local roster and thread reads: ``agent_chat_threads``, ``agent_chat_open``, ``agent_chat_log_path``, the chat-lane target resolver."""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent_runtime.dispatch_session_policy import coerce_optional_flag

from .lane import _canonical_persona_token, _chat_lane_session_ids, _looks_like_instance_handle, _refusal, _scope_off, _session_belongs_to_chat_lane
from .remote import _remote_roster_rows, _remote_thread_read

__layer__ = "lanes"


def agent_chat_threads(*, persona_id=None, requested_by_session=None):
    if _scope_off():
        return _refusal(
            "agent_chat is disabled on this runtime (HERMES_AGENT_CHAT_SCOPE=off). "
            "Tell the operator instead of retrying."
        )

    # S2b (R-S2-12). SYNTAX first, before anything looks at the filter: an
    # ``@install/target`` that will not parse must refuse rather than fall
    # through to the local roster, which would list teammates on THIS machine
    # under a heading naming another. ``None`` means local, exactly as before.
    remote = _remote_roster_rows(persona_id)
    if remote is not None:
        return remote

    from agent_runtime import workspace_scope
    from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
    from agent_runtime.persona_assignments import (
        PersonaInstanceStore,
        canonical_persona_instance_id,
        is_canonical_persona_channel,
        resolve_default_chat_session_id_for_instance,
        safe_assignment_text,
        sender_scope_workspace_id,
    )
    from agent_runtime.persona_chat_history import persona_chat_history_summary
    from hermes_cli.harness_parts.persona import chat_target as _chat_target

    # Optional filter → the canonical persona the caller means (accepts a handle).
    # A bare persona id lists ALL of that persona's instances; a personainst_*
    # handle narrows to THAT specific instance.
    wanted_persona = None
    wanted_instance_id = None
    filter_token = str(persona_id or "").strip()
    if filter_token:
        try:
            wanted_persona = _chat_target._resolve_mission_chat_persona_id(filter_token, filter_token)
        except ValueError as exc:
            return _refusal(safe_assignment_text(str(exc), limit=240), error_kind="unsupported_persona")
        if _looks_like_instance_handle(filter_token):
            wanted_instance_id = canonical_persona_instance_id(filter_token, persona_id=wanted_persona)

    cfg = load_agent_runtime_config()
    store = PersonaInstanceStore()
    store.ensure_for_personas(list(ensure_persisted_personas(cfg)))
    instances = store.list_all()

    # The DEFAULT / bare-persona listing is the sender-scoped ADDRESSABLE roster:
    # each persona's canonical row is shadowed behind an in-scope placement, and
    # out-of-scope placements are hidden — so an agent is offered the deliberate
    # placements on its own level, not the plumbing canonical rows. Sender scope
    # comes from the caller's chat-root session (threaded from the registry
    # handler), falling back to the active workspace. An explicit personainst_*
    # filter (wanted_instance_id) is deliberate targeting and BYPASSES the shadow:
    # that exact instance stays listable cross-workspace (ruling — explicit handle
    # targeting is never shadowed).
    if wanted_instance_id is None:
        scope_workspace_id = sender_scope_workspace_id(
            requested_by_session, instance_store=store
        )
        instances = workspace_scope.addressable_roster(
            instances,
            scope_workspace_id=scope_workspace_id,
            is_canonical=is_canonical_persona_channel,
        )

    # Title / last-activity / message-count come from the SAME projection the
    # persona-chat-history frame uses; keyed by the session the row renders under.
    history_by_session: dict[str, dict] = {}
    try:
        for row in persona_chat_history_summary(persona_instances=instances):
            session_id = row.get("session_id")
            if session_id:
                history_by_session[session_id] = row
    except Exception:  # pragma: no cover - defensive; a projection glitch must not blank the list
        history_by_session = {}

    # ONE ROW PER INSTANCE: a persona can run more than one live instance
    # (canonical primary + placement-backed siblings). Each is addressed by its
    # OWN handle and threads its OWN default session — collapsing them to the
    # persona's canonical channel would make siblings unreachable/invisible.
    threads = []
    seen_handles: set[str] = set()
    for instance in instances:
        instance_persona = safe_assignment_text(getattr(instance, "persona_id", None), limit=160)
        instance_handle = safe_assignment_text(getattr(instance, "id", None), limit=160)
        if not instance_persona or not instance_handle:
            continue
        # Only real, reachable teammates: the address must resolve as an
        # agent_chat_send target (skips mothballed/unroutable rows honestly).
        try:
            reachable_persona = _chat_target._resolve_mission_chat_persona_id(instance_persona, instance_persona)
        except ValueError:
            continue
        if wanted_persona is not None and _canonical_persona_token(reachable_persona) != _canonical_persona_token(wanted_persona):
            continue
        if wanted_instance_id is not None and instance_handle != wanted_instance_id:
            continue
        if instance_handle in seen_handles:
            continue
        seen_handles.add(instance_handle)
        # Resolve THIS instance's default thread WITHOUT minting — honest "no
        # thread yet" when it has never chatted.
        session_id = resolve_default_chat_session_id_for_instance(
            store, persona_id=reachable_persona, persona_instance_id=instance_handle
        )
        entry = {
            "persona_id": reachable_persona,
            "persona_instance_id": instance_handle,
            "display_name": safe_assignment_text(getattr(instance, "display_name", None), limit=120) or instance_handle,
            "handle": instance_handle,
            "session_id": session_id,
            "has_thread": bool(session_id),
        }
        row = history_by_session.get(session_id) if session_id else None
        if row is not None:
            entry["title"] = row.get("title")
            entry["last_activity"] = row.get("updated_at")
            entry["message_count"] = row.get("message_count")
        threads.append(entry)

    threads.sort(key=lambda item: (0 if item["has_thread"] else 1, item["persona_id"], item["handle"]))
    return json.dumps({"ok": True, "count": len(threads), "threads": threads}, default=str)


def _resolve_chat_lane_target(persona_id, *, requested_by_session=None, verb="agent_chat_open"):
    """Resolve a teammate address to THIS caller's chat lane with them.

    ONE authority for "which thread is *our* thread with this teammate", shared
    by the read-only companions: ``agent_chat_open`` reads its bounded tail,
    ``agent_chat_log_path`` hands over its live log file. Keeping the addressing
    and default-thread resolution here is what makes the scope guard impossible
    to drift between the two — a widening in one would otherwise be invisible in
    the other.

    Returns ``(target, refusal_json)``; exactly one of the two is ``None``.
    """

    from agent_runtime import workspace_scope
    from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
    from agent_runtime.persona_assignments import (
        PersonaInstanceStore,
        canonical_chat_instance_id,
        is_canonical_persona_channel,
        resolve_default_chat_session_id_for_instance,
        safe_assignment_text,
        sender_scope_workspace_id,
    )
    from hermes_cli.harness_parts.persona import chat_target as _chat_target

    target = str(persona_id or "").strip()
    if not target:
        return None, _refusal(f"{verb} requires a persona_id.")
    try:
        resolved_persona = _chat_target._resolve_mission_chat_persona_id(target, target)
    except ValueError as exc:
        return None, _refusal(
            safe_assignment_text(str(exc), limit=240), error_kind="unsupported_persona"
        )
    # A personainst_* handle targets THAT specific instance's thread (a persona may
    # run several) and is used as-is; a BARE persona id is resolved through the
    # sender-scoped addressable roster below (placements shadow canonical), not
    # collapsed straight onto the canonical channel.
    target_instance_id = target if _looks_like_instance_handle(target) else None

    cfg = load_agent_runtime_config()
    store = PersonaInstanceStore()
    store.ensure_for_personas(list(ensure_persisted_personas(cfg)))

    # A BARE persona resolves through the sender-scoped ADDRESSABLE roster: a
    # single in-scope placement is the target (placements shadow canonical), so
    # "open your thread with qa" reviews the deliberate placement's lane, not the
    # plumbing canonical channel. With no in-scope placement (or two — which the
    # send guard would refuse) the canonical channel is the fallback. An explicit
    # personainst_* handle is deliberate targeting and is used as-is, never
    # shadowed.
    if target_instance_id is None:
        scope_workspace_id = sender_scope_workspace_id(
            requested_by_session, instance_store=store
        )
        addressable = workspace_scope.addressable_roster(
            (
                instance
                for instance in store.list_all()
                if getattr(instance, "persona_id", None) == resolved_persona
            ),
            scope_workspace_id=scope_workspace_id,
            is_canonical=is_canonical_persona_channel,
        )
        placements = [
            instance
            for instance in addressable
            if not is_canonical_persona_channel(instance)
        ]
        if len(placements) == 1:
            target_instance_id = placements[0].id

    return (
        SimpleNamespace(
            persona=resolved_persona,
            instance_id=target_instance_id,
            handle=canonical_chat_instance_id(resolved_persona, target_instance_id),
            default_session=resolve_default_chat_session_id_for_instance(
                store, persona_id=resolved_persona, persona_instance_id=target_instance_id
            ),
            store=store,
        ),
        None,
    )


def agent_chat_open(*, persona_id, session_id=None, limit=20, requested_by_session=None):
    if _scope_off():
        return _refusal(
            "agent_chat is disabled on this runtime (HERMES_AGENT_CHAT_SCOPE=off). "
            "Tell the operator instead of retrying."
        )

    from agent_runtime.peer_directory import read_chat_lane_tail

    # S2b (R-S2-12). SYNTAX first, before anything looks at the target, for
    # ``agent_chat_send``'s reason: an ``@install/target`` that will not parse
    # must refuse rather than fall through to the local lane, because falling
    # through would read a thread on THIS machine when the caller named another.
    # ``None`` is the ordinary case and means local — a property of the parser
    # rather than a default.
    remote = _remote_thread_read(
        persona_id, session_id=session_id, limit=limit
    )
    if remote is not None:
        return remote

    # ONE implementation, two doors: this body and ``peer.thread.read`` both
    # call ``read_chat_lane_tail``. The lane guard is what stands between
    # "review our thread" and "read any transcript on this machine", and a
    # second copy of it for the far door would be a second place to widen it by
    # accident.
    data = read_chat_lane_tail(
        persona_id,
        session_id=session_id,
        limit=limit,
        requested_by_session=requested_by_session,
    )
    return json.dumps(data, default=str)


def agent_chat_log_path(
    *, persona_id, session_id=None, all_threads=None, requested_by_session=None
):
    """Hand back the PATH of a teammate thread's live transcript log.

    The 40-message tail ``agent_chat_open`` returns is the right size for "what
    did we last say"; it is the wrong tool for "search this whole thread" or
    "watch what they are doing right now". SessionDB is not greppable, so the
    runtime keeps an append-only JSONL mirror per session
    (``agent_runtime/chat_live_log.py``) and this tool tells the caller where it
    is. The head agent then uses its OWN file tools on it — no new transport, no
    payload in the tool result, no context flood.

    Live, not an export: the file keeps growing while the teammate works (message
    lines from the persist chokepoints, compact tool lines from the chat progress
    sink), so a caller can tail it mid-task.

    Scope: IDENTICAL to ``agent_chat_open`` — the caller's shared threads with
    that teammate only, via ``_resolve_chat_lane_target`` +
    ``_session_belongs_to_chat_lane``. Handing over a filesystem path is if
    anything a stronger capability than reading a tail, so it gets exactly the
    same guard and the same typed ``foreign_session`` refusal.
    """

    if _scope_off():
        return _refusal(
            "agent_chat is disabled on this runtime (HERMES_AGENT_CHAT_SCOPE=off). "
            "Tell the operator instead of retrying."
        )

    from agent_runtime.chat_live_log import chat_live_log_stats, ensure_chat_live_log

    target, refusal = _resolve_chat_lane_target(
        persona_id, requested_by_session=requested_by_session, verb="agent_chat_log_path"
    )
    if refusal is not None:
        return refusal

    requested_session = (str(session_id).strip() or None) if session_id else None
    if requested_session is not None:
        if not _session_belongs_to_chat_lane(
            requested_session, handle=target.handle, default_session=target.default_session
        ):
            return _refusal(
                f"session {requested_session!r} is not part of {target.persona}'s chat lane; "
                "agent_chat_log_path only hands over logs for your shared threads with the "
                "target, not arbitrary sessions.",
                error_kind="foreign_session",
                target_persona=target.persona,
            )
        wanted = [requested_session]
    elif coerce_optional_flag(all_threads) is True:
        wanted = _chat_lane_session_ids(target)
    else:
        wanted = [target.default_session] if target.default_session else []

    threads = []
    for candidate in wanted:
        # THIS is the lane that materializes history. The chat persist seams
        # deliberately never do (they would pay the full curated projection —
        # turn-journal re-parse per row — inside a live turn); they create a
        # header-only file and append. A deliberate agent request can afford the
        # read, so it completes any file still marked backfill_pending.
        path = ensure_chat_live_log(candidate, materialize=True)
        if path is None:
            continue
        stats = chat_live_log_stats(candidate) or {}
        threads.append(
            {
                "session_id": candidate,
                "path": str(path),
                "bytes": stats.get("bytes", 0),
                "message_count": stats.get("message_count", 0),
                "tool_count": stats.get("tool_count", 0),
                "last_activity": stats.get("last_activity"),
                "rotated_path": stats.get("rotated_path"),
                # Honest on both ways history can be short: never materialized,
                # or materialized only up to the declared bound. Either way the
                # file may start later than the conversation does.
                "history_complete": not (
                    stats.get("backfill_pending", False)
                    or stats.get("backfill_truncated", False)
                ),
                # Not a snapshot: this file keeps growing while the teammate
                # works, so re-reading it later shows new activity.
                "live": True,
            }
        )

    return json.dumps(
        {
            "ok": True,
            "target_persona": target.persona,
            "handle": target.handle,
            "count": len(threads),
            "threads": threads,
            "format": "jsonl",
            # Say exactly what the growing part of the file carries. An agent
            # that believes "full history, live" would draw wrong conclusions
            # from the absence of a mid-turn steer it knows was sent.
            "live_coverage": (
                "appended as they happen: operator/relay messages, mid-turn steers "
                "(steered: true), each turn's final reply, and tool start/finish "
                "lines. The runtime's non-final rows (intermediate assistant messages "
                "between tool calls) are NOT appended live — they appear in the "
                "materialized history, not in the live tail."
            ),
            "next_expected": (
                "grep / tail the path with your own file tools; each line is JSON with "
                "{ts, kind: message|tool, ...}. Re-read later to see new activity."
            )
            if threads
            else "no thread with this teammate yet — nothing to read",
        },
        default=str,
    )
