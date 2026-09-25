"""The chat verbs: ``runtime.persona_instance.open_chat``, ``runtime.persona.prewarm``,
``runtime.chat.message`` and ``runtime.chat.steer``.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ

from agent_runtime.serve_rpc.protocol import RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_chat_message",
    "_runtime_chat_steer",
    "_runtime_persona_instance_open_chat",
    "_runtime_persona_prewarm",
]


# ── runtime.persona.instance.open_chat ───────────────────────────────────────


@method("runtime.persona.instance.open_chat", tier=TIER_CONSOLE)
def _runtime_persona_instance_open_chat(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Open — or mint — the chat root a persona instance is bound to.

    Params: ``persona_id`` (required); ``persona_instance_id``, ``session_id``,
    ``new_session``, ``kill_active``, ``idempotency_key`` (alias
    ``client_message_id``), ``requested_by``, ``correlation_id`` (optional).

    Result: the CLI verb's own success row, verbatim. It carries ``session_id``
    and ``persona_instance_id`` on BOTH arms — which is not a coincidence but
    the contract: the launcher's bridge reads exactly those two keys back off
    ``persona.instance.open_chat`` today, and this method exists so that reader
    is fed unchanged when the gesture is aimed at another install. The
    ``--new-session`` arm adds ``mission_chat_root_id``, ``selected``,
    ``superseded``, ``idempotent_replay`` and ``mint_receipt_state``; the
    rebind arm adds ``previous_session_id``, ``binding_receipt`` and ``mode``.

    **Why this method exists at all** (plan ``remote-chat-parity.md``, ruling
    R-C5). The office verbs, the two chat-turn verbs and both agent-lifecycle
    verbs are on this lane, so a console aimed at another install could place an
    agent, move it, retire it and talk to it — and could not START the
    conversation, because opening a chat had only an argv lowering and the argv
    lane is refused to a remote aim on purpose. Ruling R-C4 makes that the
    general rule: a write lane the launcher touches gets a method before its
    launcher half is built, and the argv arm becomes a compatibility fallback
    with a deletion condition.

    **Tier: ``console``, and NOT on ``LOCAL_CONSOLE_METHODS``.** A paired
    console device opening a chat on the install it is aimed at is the feature,
    not a hole — the same argument ``runtime.chat.message`` already carries at
    length, and the stronger one, since a chat turn RUNS an agent with tools and
    this only binds a pointer and mints a transcript row. The restricted set is
    for verbs whose subject is the machine owner's own session (the scope
    pointers, the peer directory), and a chat root is not one.

    A TRANSLATION SHIM, exactly like ``_runtime_agent_create`` — with the shim
    landing one step lower, the way ``_runtime_chat_message``'s does: the
    sequence is an argparse handler rather than a ``perform_*``, so the service
    builds that handler's namespace and takes the payload off its
    ``payload_sink`` seam. Everything below is envelope work; every refusal
    string, ``error_kind`` and ``next_expected`` comes out of the CLI handler
    unchanged, because a second spelling here would be the copy the discipline
    exists to abolish. See :mod:`agent_runtime.persona_open_chat`.

    Adding this name GROWS the manifest's ``methods`` set without moving
    ``RPC_CONTRACT_VERSION``: a manifest is a set plus an integer, and the
    integer moves only when an existing method's shape changes incompatibly.
    """

    from agent_runtime.persona_open_chat import perform_persona_instance_open_chat

    outcome = perform_persona_instance_open_chat(
        params, caller=context.caller if context is not None else None
    )
    if outcome.refusal is not None:
        refusal = outcome.refusal
        return err(rid, refusal.code, refusal.message, refusal.data)
    return ok(rid, outcome.result)


# ── runtime.persona.prewarm ──────────────────────────────────────────────────


@method("runtime.persona.prewarm", tier=TIER_READ)
def _runtime_persona_prewarm(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Fill this persona type's visibility memos BEFORE a create needs them.

    Params: ``persona_id`` (required); ``correlation_id`` (optional, echoed).

    Result::

        {persona_id, accepted: true, state: "started" | "already_running",
         correlation_id?}

    Fire-and-forget by contract. The reply says a warm was ACCEPTED, never that
    it finished — the whole point is that the caller (the launcher, on palette
    open) is doing something else while it runs, and a caller that awaited the
    warm would have moved the cold cost rather than removed it. So there is no
    completion field to wait on and none is coming: the observable effect is the
    NEXT ``runtime.agent.create``'s ``phases.instance_ms``, which the drop log
    already prints.

    Additive in the strongest sense. It registers a new method rather than
    changing one, it writes no store state, emits no event and mints no id, and
    a runtime nobody ever calls it on behaves exactly as it does today. A client
    that does not find ``runtime.persona.prewarm`` in the ``rpc`` manifest block
    simply keeps paying the cold create — which is why the contract integer does
    not move for it (see :func:`manifest`).

    Why the refusals are the CREATE's refusals. ``persona_not_found`` /
    ``persona_roster_unavailable`` come out of ``agent_create``'s own spellings,
    codes included, so a launcher that prewarms an id and then creates it can
    never be told two different stories about that id. The one reason this verb
    owns alone is ``profile_persona_not_prewarmable`` — the D-U1 carve-out the
    create accepts and a prewarm provably cannot serve; the service docstring
    says why.

    A failure INSIDE the warm never reaches here. It happens on the worker,
    after this frame is already on the wire, and is swallowed-and-logged there:
    a cache that did not fill costs latency, never correctness.

    On the inline-dispatch budget. ``serve.py`` answers this lane on the reader
    loop itself, on the stated grounds that a method touches a handful of small
    JSON files and is done before the loop misses anything. That still holds:
    the only synchronous work here is the roster read that decides accept-vs-
    refuse, which is the same read ``runtime.agent.create`` already performs
    inline on the same loop. The seconds — registry populate, toolset sweep,
    readiness — are exactly what moves to the worker, which is the point.
    """

    from agent_runtime.persona_prewarm import request_persona_prewarm

    outcome = request_persona_prewarm(params)
    if outcome.refusal is not None:
        refusal = outcome.refusal
        return err(rid, refusal.code, refusal.message, refusal.data)
    return ok(rid, outcome.result)


# ── runtime.chat.message / runtime.chat.steer ────────────────────────────────
#
# Gateway Stage 3. The plan's Stage 3 sketch said "RPC where methods exist,
# op/argv lane otherwise — same union", and that union has a hole a device falls
# through: ``mission.chat.*`` has no methods, it lowers to argv, and Stage 1
# REFUSES the argv lane to devices outright (``serve.py``'s ``_is_gateway``
# branch — the refusal that stops a ``read`` device from sending as argv what it
# was refused on the method lane). A remote device therefore could not send a
# chat turn at all, and chat is what this gateway is for.
#
# So the two chat-turn verbs are ported to the method lane, which is the
# direction ``archive/runtime-rpc-call-half.md`` already had, and the scope is
# deliberately those two and not the argv surface. The local stdio lane keeps
# its argv path byte-for-byte: nothing here changes how the launcher's local
# session sends a turn today.


@method("runtime.chat.message", tier=TIER_CONSOLE)
def _runtime_chat_message(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Send ONE Mission Control chat turn. Accepts and hands off; never blocks.

    Params: ``turn_request_id``, ``persona_id``, ``message`` (required);
    ``session_id``, ``persona_instance_id``, ``workspace_id``, ``title``,
    ``new_session``, ``stream``, ``max_seconds``, ``correlation_id`` (optional).

    Result::

        {turn_request_id, request_id, accepted: true, state: "accepted",
         verb, idempotent_replay, settled, exit_code?, correlation_id?}

    **The ack is an ACCEPT, not a reply**, and that is forced by the lane rather
    than chosen: this dispatcher answers INLINE on the reader loop (see the
    method-lane comment in ``serve.py``, which names chat turns as the reason
    the worker pool exists), so a method that ran a turn would stall every other
    client attached to this serve for its whole length. The turn's frames —
    deltas when ``stream`` is asked for, the final ``--json`` payload always —
    ride the existing per-request frame lane under the returned ``request_id``,
    which is the same lane the local launcher already reads. No second streaming
    transport is invented; the socket lane has carried per-request frames since
    it existed.

    **Tier: ``console``, and honestly rather than conveniently.** The tempting
    read is that a chat turn is not a level mutation, so it should be something
    softer — and R11's own sentence ("a paired console device may chat") can be
    satisfied by a new ``chat`` word. It should not be, for two reasons. The
    first is what the verb DOES: a chat turn runs an agent with tools. It can
    write files, spawn dispatches, install skills and place agents, so a tier
    below ``console`` would be a door around ``console`` — the ``read`` device
    refused ``runtime.agent.retire`` could ask an agent to retire one. The
    second is mechanical and would have bitten immediately:
    ``call_authorization.authorize_call``'s device arm is an EQUALITY against
    the stored word, not an ordering, so a new ``chat`` tier would have refused
    every already-paired ``console`` device the very thing R11 says it may do.
    Declaring chat at ``console`` satisfies R11 exactly, keeps the vocabulary at
    two words, and changes no predicate. If an ``admin``/``chat`` vocabulary is
    ever wanted it is still R11's question, and the honest first move there is
    to make the device arm an ordering — which is a decision, not a constant.

    **Exactly-once, and the correction it rests on.** The plan records that
    mission-chat send has no server-side dedupe ("no ``turn_request_id``
    anywhere", re-verified 2026-08-27). The grep was right and the conclusion
    was wrong: mission chat has carried exactly-once under the name
    ``client_message_id`` plus the per-session turn journal since the 2026-08-24
    incident, replying ``idempotent_replay: True`` with the committed reply,
    ``chat_turn_duplicate_in_flight`` while the turn runs, and
    ``chat_turn_outcome_unknown`` when the provider outcome cannot be proven.
    ``turn_request_id`` is therefore not a second key — it is passed to
    ``--client-message-id`` unchanged, so the journal that already owns this
    keys on exactly what the device sent. What the reservation
    (``chat_turn_reservations``) adds is only the ACCEPT window the journal
    cannot cover, because the journal's first write happens inside the chat-root
    lease, after a worker is already running. See that module's docstring.

    A TRANSLATION SHIM, exactly like ``_runtime_agent_create`` — with the shim
    landing one step lower. Mission chat's service is an argparse handler, not a
    ``perform_*`` function, and its one existing second door
    (``dispatch_delivery.deliver_via_mission_chat``) reaches it by building a
    namespace. This door builds ARGV, which the worker dispatches through the
    same argparse tree a local send uses, so a remote turn and a local turn are
    the same execution rather than two implementations that agree today.
    """

    from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD, perform_chat_turn

    outcome = perform_chat_turn(
        params,
        verb=CHAT_MESSAGE_METHOD,
        spawn=None if context is None else context.spawn_chat_turn,
    )
    if outcome.refusal is not None:
        refusal = outcome.refusal
        return err(rid, refusal.code, refusal.message, refusal.data)
    return ok(rid, outcome.result)


@method("runtime.chat.steer", tier=TIER_CONSOLE)
def _runtime_chat_steer(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Steer the chat turn currently running on a root. Accepts and hands off.

    Params: ``turn_request_id``, ``session_id``, ``message`` (required);
    ``persona_id``, ``persona_instance_id``, ``correlation_id`` (optional).

    Result: ``runtime.chat.message``'s, with ``verb`` naming this method.

    Everything in that method's docstring applies here — the accept-not-reply
    contract, the ``console`` tier, and the ``turn_request_id`` →
    ``client_message_id`` identity — and one thing is specific to steer:
    ``harness mission-chat steer`` already REQUIRES ``--client-message-id``,
    where the send merely accepts it. So the remote steer is the verb whose
    exactly-once key was never optional, and the reservation over it is the
    accept-window cover rather than the key itself.

    It rides the worker lane rather than answering inline even though a steer is
    cheap, and that is a deliberate uniformity: ``_CHAT_TURN_COMMANDS`` in
    ``serve.py`` counts BOTH ``mission-chat message`` and ``mission-chat steer``
    as in-flight chat turns for the drain ledger, and a steer that skipped the
    worker would be a chat turn the recycle protection could not see.
    """

    from agent_runtime.chat_turn import CHAT_STEER_METHOD, perform_chat_turn

    outcome = perform_chat_turn(
        params,
        verb=CHAT_STEER_METHOD,
        spawn=None if context is None else context.spawn_chat_turn,
    )
    if outcome.refusal is not None:
        refusal = outcome.refusal
        return err(rid, refusal.code, refusal.message, refusal.data)
    return ok(rid, outcome.result)
