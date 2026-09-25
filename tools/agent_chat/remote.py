"""The far-install reads: a remote thread, a remote roster, and ``agent_chat_installs``."""

from __future__ import annotations

import json

from .lane import _bounded_limit, _refusal, _scope_off

__layer__ = "lanes"


def _remote_thread_read(persona_id, *, session_id, limit):
    """The ``@install/`` branch of :func:`agent_chat_open`, or ``None`` for local.

    Split out rather than inlined so the local path above reads as it did before
    S2b: one call to the shared reader, nothing else.
    """

    from agent_runtime.gateway_targets import (
        TargetRefusal,
        parse_install_target,
        peer_store_root,
        resolve_install_target,
    )

    parsed = parse_install_target(persona_id)
    if parsed is None:
        return None
    if isinstance(parsed, TargetRefusal):
        return _refusal(
            parsed.message, error_kind=parsed.reason, target_persona=persona_id
        )

    if not str(session_id or "").strip():
        # **There is no "our default thread" on another install.** Locally the
        # default session is the one this pair has been using; across a boundary
        # the far install has its own default, which is the most recently
        # established thread with ANYBODY and is almost never the one the caller
        # means. So the thread must be named — and the refusal says where the
        # name came from, because the dispatch delivery already printed it.
        return _refusal(
            f"{persona_id} is on another install, and there is no shared default "
            "thread across installs. Name the thread: pass session_id — the "
            "session_id your dispatch delivery reported as 'Their thread'.",
            error_kind="remote_session_required",
            target_persona=persona_id,
        )

    root = peer_store_root()
    resolved = resolve_install_target(root, parsed)
    if isinstance(resolved, TargetRefusal):
        extra = (
            {"candidates": list(resolved.candidates)} if resolved.candidates else {}
        )
        return _refusal(
            resolved.message,
            error_kind=resolved.reason,
            target_persona=persona_id,
            **extra,
        )

    from tools.agent_chat_remote import call_peer_method

    outcome = call_peer_method(
        root,
        resolved.install_id,
        "peer.thread.read",
        {
            "target": parsed.target,
            "session_id": str(session_id).strip(),
            # Coerced HERE rather than passed through, because the far handler
            # fences ``limit`` as an int and refuses anything else — and a
            # provider that hands a tool its numbers as strings would otherwise
            # turn a legal call into an invalid-params refusal the caller cannot
            # act on. The far side still clamps to 1..40; this only makes the
            # value the right TYPE.
            "limit": _bounded_limit(limit),
        },
    )
    refusal = outcome.get("refusal")
    if refusal:
        return _refusal(
            str(refusal.get("message") or refusal.get("reason")),
            error_kind=str(refusal.get("reason")),
            target_persona=persona_id,
        )
    result = dict(outcome.get("result") or {})
    result["install"] = {
        "install_id": resolved.install_id,
        "display_name": resolved.display_name,
    }
    # Spelled the way the grammar accepts, so the answer names an address the
    # caller could use again rather than a bare persona id that would resolve
    # locally.
    result["target_persona"] = f"@{parsed.install_ref}/{result.get('target_persona') or parsed.target}"
    return json.dumps(result, default=str)


def _remote_roster_rows(persona_id):
    """The ``@install/`` branch of :func:`agent_chat_threads`, or ``None`` locally.

    Answers in the LOCAL threads-row shape rather than in the peer method's own
    projection shape, because a tool that returned two different row schemas
    depending on where the teammate lives would make every consumer branch on
    residency to read a name. What differs is the ``handle`` — spelled as the
    full ``@install/handle`` address, so a row an agent reads is a row it can
    send to — and ``has_thread``, which is ``null`` rather than ``false``: this
    install genuinely does not know whether the caller has a thread with that
    far teammate, and ``false`` would be a claim.
    """

    from agent_runtime.gateway_targets import (
        TargetRefusal,
        parse_install_target,
        peer_store_root,
        resolve_install_target,
    )

    parsed = parse_install_target(persona_id)
    if parsed is None:
        return None
    if isinstance(parsed, TargetRefusal):
        # ``@mac/`` is refused by the parser today (``install_qualifier_target_empty``)
        # and STAYS refused: the verb for "everyone on that machine" is
        # ``agent_chat_installs``, and letting an empty target mean "all" would
        # give one spelling two meanings.
        return _refusal(
            parsed.message, error_kind=parsed.reason, target_persona=persona_id
        )

    root = peer_store_root()
    resolved = resolve_install_target(root, parsed)
    if isinstance(resolved, TargetRefusal):
        extra = {"candidates": list(resolved.candidates)} if resolved.candidates else {}
        return _refusal(
            resolved.message,
            error_kind=resolved.reason,
            target_persona=persona_id,
            **extra,
        )

    from agent_runtime.gateway_peers import cache_peer_roster
    from tools.agent_chat_remote import call_peer_method

    outcome = call_peer_method(
        root,
        resolved.install_id,
        "peer.roster.list",
        {"target": parsed.target},
    )
    refusal = outcome.get("refusal")
    if refusal:
        return _refusal(
            str(refusal.get("message") or refusal.get("reason")),
            error_kind=str(refusal.get("reason")),
            target_persona=persona_id,
        )
    result = outcome.get("result") or {}
    rows = [row for row in (result.get("rows") or []) if isinstance(row, dict)]

    # Cache what we just fetched, so the HUD's install lines can render a roster
    # without dialling anything (R-IP11). The fetch already happened; keeping it
    # is free, and NOT keeping it would mean the only way to see who is on
    # another machine is to ask again every turn.
    try:
        cache_peer_roster(
            root,
            resolved.install_id,
            workspace_id=result.get("workspace_id"),
            rows=rows,
        )
    except Exception:  # pragma: no cover - bookkeeping is never the work
        pass

    wanted = str(parsed.target or "").strip()
    install_block = {
        "install_id": resolved.install_id,
        "display_name": resolved.display_name,
    }
    threads = []
    for row in rows:
        handle = str(row.get("handle") or "")
        persona = str(row.get("persona_id") or "")
        if wanted and wanted not in {handle, persona}:
            continue
        threads.append(
            {
                "persona_id": persona,
                "persona_instance_id": handle,
                "handle": f"@{parsed.install_ref}/{handle}",
                "display_name": row.get("label") or handle,
                "has_thread": None,
                "last_activity": row.get("last_turn_at"),
                "install": install_block,
            }
        )
    return json.dumps(
        {
            "ok": True,
            "count": len(threads),
            "install": install_block,
            "workspace_id": result.get("workspace_id"),
            "threads": threads,
        },
        default=str,
    )


def agent_chat_installs(*, install=None, requested_by_session=None):
    """Which other machines this install can reach, and optionally who is on one.

    ``requested_by_session`` is accepted and NOT used, deliberately: every
    handler in this module takes it (the registry threads it in from
    ``kw["session_id"]``), and a directory of MACHINES has no sender scope to
    narrow — the peers of an install are the same set whoever asks. Dropping the
    parameter would make this the one tool whose registration reads differently
    for a reason nobody could see from the call site.

    Two shapes from one verb, and the split is the network cost: with no
    ``install`` it reads THIS install's own two files and DIALS NOTHING; with
    one, it makes exactly one call to that machine and caches what comes back.
    An operator (or an agent) orienting itself should not have to spend a round
    trip per paired machine to find out which ones are worth addressing.

    The rows are ``usable_peers`` verbatim — the SAME predicate the resolver
    reads — so every install listed here is one a send would resolve, and every
    paired install NOT listed is one a send would refuse. A directory that
    offered an edge the resolver had written off would be a list an agent
    learns to distrust.
    """

    if _scope_off():
        return _refusal(
            "agent_chat is disabled on this runtime (HERMES_AGENT_CHAT_SCOPE=off). "
            "Tell the operator instead of retrying."
        )

    from agent_runtime.gateway_peers import usable_peers
    from agent_runtime.gateway_targets import peer_store_root

    root = peer_store_root()

    wanted = str(install or "").strip()
    if wanted:
        return _install_roster(root, wanted)

    try:
        peers = usable_peers(root)
    except Exception as exc:  # pragma: no cover - defensive; an unreadable store
        return _refusal(
            f"this install's peer store could not be read ({type(exc).__name__}), "
            "so no other install can be named.",
            error_kind="peer_store_unreadable",
        )

    installs = []
    for peer in peers:
        cache = peer.cache
        installs.append(
            {
                # The spelling the grammar accepts — a display name when it is
                # unique, otherwise the id — so a value read here is an address
                # ``@ref/target`` resolves rather than one the resolver would
                # refuse as ambiguous.
                "ref": peer.ref,
                "install_id": peer.record.peer_install_id,
                "display_name": (
                    (cache.announced_display_name if cache is not None else None)
                    or peer.record.display_name
                ),
                "endpoints_count": len(peer.record.endpoints),
                "approved_at": peer.record.approved_at,
                "expires_at": peer.record.expires_at,
                "reachability": cache.reachability if cache is not None else "unknown",
                "last_seen": cache.last_seen if cache is not None else None,
                "roster_cached_at": (
                    (cache.roster or {}).get("fetched_at")
                    if cache is not None and isinstance(cache.roster, dict)
                    else None
                ),
            }
        )
    return json.dumps(
        {"ok": True, "count": len(installs), "installs": installs}, default=str
    )


def _install_roster(root, install_ref: str):
    """One install's roster of addressable agents, fetched and cached."""

    from agent_runtime.gateway_peers import cache_peer_roster
    from agent_runtime.gateway_targets import TargetRefusal, resolve_install_ref
    from tools.agent_chat_remote import call_peer_method

    resolved = resolve_install_ref(root, install_ref)
    if isinstance(resolved, TargetRefusal):
        extra = {"candidates": list(resolved.candidates)} if resolved.candidates else {}
        return _refusal(resolved.message, error_kind=resolved.reason, **extra)

    outcome = call_peer_method(
        root, resolved.peer_install_id, "peer.roster.list", {}
    )
    refusal = outcome.get("refusal")
    if refusal:
        return _refusal(
            str(refusal.get("message") or refusal.get("reason")),
            error_kind=str(refusal.get("reason")),
        )
    result = outcome.get("result") or {}
    rows = [row for row in (result.get("rows") or []) if isinstance(row, dict)]
    try:
        cache_peer_roster(
            root,
            resolved.peer_install_id,
            workspace_id=result.get("workspace_id"),
            rows=rows,
        )
    except Exception:  # pragma: no cover - bookkeeping is never the work
        pass
    return json.dumps(
        {
            "ok": True,
            "install": {
                "install_id": resolved.peer_install_id,
                "display_name": resolved.display_name,
            },
            "workspace_id": result.get("workspace_id"),
            "count": len(rows),
            "truncated": bool(result.get("truncated")),
            # Each row spelled as the FULL address, so a roster line is
            # actionable rather than merely informative.
            "roster": [
                {**row, "address": f"@{install_ref}/{row.get('handle')}"}
                for row in rows
            ],
        },
        default=str,
    )
