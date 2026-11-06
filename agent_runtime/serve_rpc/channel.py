"""``runtime.channel.message``: one inbound platform message from the owner's own external gateway.

Plan ``docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md`` §2 D2–D4
(row ``RT-EXTERNAL-GATEWAY-CHANNEL-MESSAGE-VERB``, owner ruling C 2026-11-05). The gateway owns the
platform side — polling, webhooks, formatting, its bot token; hermes never sees a token. This verb
owns the runtime side, as two existing doors and nothing new:

1. **Which conversation.** ``(the proven device, channel_key)`` → ONE independent chat root of the
   bound instance, minted by ``runtime.persona.instance.open_chat``'s own ``new_session`` door with
   the idempotency key :func:`gateway_channel.channel_session_key` derives from the PAIR, so the
   first message mints it and every later one replays it. The pair, never the key alone: two
   gateways that both call a conversation ``telegram:42`` must not share a transcript.
2. **The turn.** ``runtime.chat.message``'s own ``perform_chat_turn`` on that root: the accept-not-
   reply ack, exactly-once on ``turn_request_id``, the reply on the per-request frame lane.

The root is stamped in its session meta with ``channel_source: "channel:<device name>"`` and
``channel_key``, and titled with both, so Mission Control lists it among the instance's chats and
says where it came from. Admission is the dispatcher's: a channel credential only, bound to the
named instance, while the external-access switch is on (``agent_runtime.gateway_channel``).
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["CHANNEL_MESSAGE_METHOD_PARAMS", "_runtime_channel_message"]

#: The keys this verb honours (the manifest's ``params`` block publishes them).
CHANNEL_MESSAGE_METHOD_PARAMS: tuple[str, ...] = (
    "channel_key", "correlation_id", "persona_instance_id", "sender", "text", "turn_request_id",
)
_CHANNEL_KEY_LIMIT = 200
_SENDER_LIMIT = 80


def _refuse(rid: Any, code: int, reason: str, message: str) -> dict:
    return err(rid, code, message, {"reason": reason})


def _channel_param(params: dict, key: str, limit: int) -> str | None:
    value = params.get(key)
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()) if key != "text" else value.strip()
    return text[:limit] if text and (key == "text" or text.isprintable()) else None


@method("runtime.channel.message", tier=TIER_CONSOLE)
def _runtime_channel_message(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Relay ONE platform message to the bound instance's conversation for ``channel_key``.

    Params: ``channel_key`` (the gateway's stable conversation id, e.g. ``telegram:<chat_id>``),
    ``text``, ``turn_request_id`` (required); ``sender`` (shown to the agent as ``<sender>: <text>``),
    ``persona_instance_id`` (must be bound; default the first bound instance), ``correlation_id``.
    ``attachments`` is refused ``channel_attachments_unsupported`` rather than ignored.

    Result: ``runtime.chat.message``'s ack plus ``session_id``, ``persona_instance_id``,
    ``channel_key`` and ``session_created`` (false when the conversation already existed), and
    ``client_scope`` when the channel was paired with one (its conversations list under that account).
    """

    from agent_runtime.gateway_channel import is_channel_caller

    caller = None if context is None else context.caller
    if not is_channel_caller(caller):
        return _refuse(rid, ERR_HANDLER_FAILED, "channel_credential_required",
                       "runtime.channel.message is a channel credential's verb")
    if params.get("attachments"):
        return _refuse(rid, ERR_INVALID_PARAMS, "channel_attachments_unsupported",
                       "attachments are not relayed yet; send text")
    channel_key = _channel_param(params, "channel_key", _CHANNEL_KEY_LIMIT)
    text = _channel_param(params, "text", 100_000)
    if channel_key is None or text is None:
        return _refuse(rid, ERR_INVALID_PARAMS, "invalid_params", "channel_key and text are required strings")
    if not caller.bound_instances:
        return _refuse(rid, ERR_HANDLER_FAILED, "channel_instance_not_bound",
                       "this channel credential is bound to no persona instance")
    instance_id = _channel_param(params, "persona_instance_id", 200) or caller.bound_instances[0]
    opened = _open_conversation(rid, caller, instance_id, channel_key)
    if "error" in opened:
        return opened
    session = opened["result"]
    sender = _channel_param(params, "sender", _SENDER_LIMIT)
    return _send_turn(rid, params, context, session, f"{sender}: {text}" if sender else text, channel_key)


def _device_identity(device_id: str) -> tuple[str, str | None]:
    """The paired row's name and owning account scope (``RT-EXTERNAL-GATEWAY-CHANNEL-CLIENT-SCOPE``).

    Read from the device store, never the request: the scope a channel's conversations carry is
    what the owner bound at pairing, so a gateway cannot file its chats under another account.
    """

    try:
        from agent_runtime.gateway_targets import peer_store_root
        from agent_runtime.serve_gateway_auth import lookup_device

        record = lookup_device(peer_store_root(), device_id)
    except Exception:
        record = None
    if record is None:
        return device_id, None
    return record.name, record.client_scope


def _open_conversation(rid: Any, caller: Any, instance_id: str, channel_key: str) -> dict:
    """Mint-or-replay the (device, channel_key) root through open-chat's own ``new_session`` door."""

    from agent_runtime.gateway_channel import channel_session_key
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.persona_open_chat import perform_persona_instance_open_chat

    try:
        instance = PersonaInstanceStore().get(instance_id)
    except Exception:
        return _refuse(rid, ERR_INVALID_PARAMS, "persona_instance_not_found",
                       f"persona instance not found: {instance_id}")
    name, client_scope = _device_identity(caller.device_id)
    source = f"channel:{name}"
    outcome = perform_persona_instance_open_chat(
        {
            "persona_id": instance.persona_id,
            "persona_instance_id": instance_id,
            "new_session": True,
            "idempotency_key": channel_session_key(caller.device_id, channel_key),
            "title": f"{source} · {channel_key}",
            "requested_by": source,
            **({"client_scope": client_scope} if client_scope else {}),
        },
        caller=caller,
        select_session=False,
    )
    if outcome.refusal is not None:
        return err(rid, outcome.refusal.code, outcome.refusal.message, outcome.refusal.data)
    result = dict(outcome.result or {})
    result["persona_id"] = instance.persona_id
    result["session_created"] = not bool(result.get("idempotent_replay"))
    if client_scope:
        result["client_scope"] = client_scope
    _stamp_source(instance, result.get("session_id"), source, channel_key)
    return {"result": result}


def _stamp_source(instance: Any, session_id: Any, source: str, channel_key: str) -> None:
    """``channel_source`` / ``channel_key`` into the root's meta. Best effort: the turn still runs."""

    from contextlib import closing

    from agent_runtime.chat_session_scope import resolve_instance_chat_scope
    from agent_runtime.persona_chat_durability import default_persona_session_db, persona_session_db_for

    if not isinstance(session_id, str) or not session_id:
        return
    try:
        db = persona_session_db_for(resolve_instance_chat_scope(instance), process=default_persona_session_db)
        with closing(db) as session_db:
            session_db.patch_session_model_config(
                session_id, {"channel_source": source, "channel_key": channel_key})
    except Exception:
        return


def _send_turn(rid: Any, params: dict, context: RpcContext | None, session: dict, message: str,
               channel_key: str) -> dict:
    from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD, perform_chat_turn

    turn = {
        "turn_request_id": params.get("turn_request_id"),
        "persona_id": session["persona_id"],
        "persona_instance_id": session.get("persona_instance_id"),
        "session_id": session.get("session_id"),
        "message": message,
        **({"correlation_id": params["correlation_id"]} if params.get("correlation_id") else {}),
    }
    outcome = perform_chat_turn(turn, verb=CHAT_MESSAGE_METHOD,
                                spawn=None if context is None else context.spawn_chat_turn)
    if outcome.refusal is not None:
        return err(rid, outcome.refusal.code, outcome.refusal.message, outcome.refusal.data)
    return ok(rid, {
        **outcome.result,
        "session_id": session.get("session_id"),
        "persona_instance_id": session.get("persona_instance_id"),
        "channel_key": channel_key,
        "session_created": session["session_created"],
        **({"client_scope": session["client_scope"]} if session.get("client_scope") else {}),
    })
