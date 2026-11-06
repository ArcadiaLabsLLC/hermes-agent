"""The owner's own external gateways: what a ``channel`` credential may reach, and when.

Plan ``docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md`` (owner
ruling C, 2026-11-05). A gateway is a CLIENT of the namespace's serve over the gateway lane, holding
its own paired, revocable credential (``serve_gateway_auth``: a device row with ``kind: channel``
and ``bound_instances``). Three rules live here, each beside the predicate it needs:

* **Which agent** (D1, ``RT-EXTERNAL-GATEWAY-CHANNEL-CREDENTIAL``). ``call_authorization`` admits a
  channel caller to the chat verbs only; :func:`channel_target_refusal` then refuses a chat verb
  whose target instance — named, or owning the named session — is not one the credential is bound
  to (``channel_instance_not_bound``). A chat verb naming no target refuses too: the persona's
  default instance is not a binding. Authority is still read off the caller; the request only says
  WHICH instance it aims at, and an aim outside the binding is refused.
* **When** (D5, ``RT-EXTERNAL-GATEWAY-SWITCH-GATE``). A channel credential is honoured only while
  ``<base>/namespace-active.json`` names THIS process's namespace — the "Allow agent use outside the
  launcher" switch. :func:`external_access_on` is read at the hello and again on every call, so
  switching it off stops a connected gateway at its next turn. A serve on the base root (no
  namespace) never honours one: no record can name the base root.
* **Which conversation** (D2, ``RT-EXTERNAL-GATEWAY-CHANNEL-MESSAGE-VERB``). :func:`channel_session_key`
  derives the open-chat idempotency key from the (device, ``channel_key``) PAIR, so one platform
  conversation lands in one session and two gateways that use the same key never share one.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from typing import Any

from .call_authorization import (
    CALLER_DEVICE,
    DEVICE_KIND_CHANNEL,
    CallAuthorization,
)

__layer__ = "stores"

__all__ = [
    "CHANNEL_MESSAGE_METHOD",
    "MAX_BOUND_INSTANCES",
    "REASON_CHANNEL_INSTANCE_NOT_BOUND",
    "REASON_EXTERNAL_ACCESS_OFF",
    "channel_session_key",
    "channel_target_refusal",
    "clean_bound_instances",
    "external_access_on",
    "is_channel_caller",
]

CHANNEL_MESSAGE_METHOD = "runtime.channel.message"
#: The typed refusals. CONTRACT, not prose: a gateway branches on ``data.reason``.
REASON_CHANNEL_INSTANCE_NOT_BOUND = "channel_instance_not_bound"
REASON_EXTERNAL_ACCESS_OFF = "external_access_off"
#: A gateway is bound to a handful of agents (the plan recommends one); a cap keeps a typo'd
#: shell loop from writing a row nobody can read.
MAX_BOUND_INSTANCES = 16


def is_channel_caller(caller: Any) -> bool:
    return getattr(caller, "kind", None) == CALLER_DEVICE and getattr(caller, "device_kind", None) == DEVICE_KIND_CHANNEL


def clean_bound_instances(values: Any) -> tuple[str, ...]:
    """Printable, single-token, de-duplicated (first wins), at most :data:`MAX_BOUND_INSTANCES`."""

    out: list[str] = []
    for value in values if isinstance(values, (list, tuple)) else ():
        text = str(value or "").strip() if isinstance(value, str) else ""
        if text and len(text) <= 200 and text.isprintable() and " " not in text and text not in out:
            out.append(text)
    return tuple(out[:MAX_BOUND_INSTANCES])


def external_access_on(env: Mapping[str, str] | None = None) -> bool:
    """True only while the base root's active record names this process's namespace. Never raises."""

    from hermes_cli._namespace_bootstrap import base_root, namespace_stamp, read_active_record

    environ = os.environ if env is None else env
    namespace = namespace_stamp(environ)
    if not namespace:
        return False
    try:
        return read_active_record(base_root(environ)) == namespace
    except Exception:  # a malformed or unreadable record is the switch OFF, never on
        return False


def channel_session_key(device_id: str, channel_key: str) -> str:
    """The open-chat idempotency key for one (device, platform conversation) pair."""

    digest = hashlib.sha256(f"{device_id}\x1f{channel_key}".encode("utf-8")).hexdigest()
    return f"channel-{digest[:40]}"


def _refuse(reason: str, detail: str, caller: Any) -> CallAuthorization:
    return CallAuthorization(ok=False, reason=reason, tier="console", caller_kind=str(caller.kind), detail=detail)


def _targets(method: str, params: dict) -> list[str]:
    from .persona_assignments.identity import chat_session_owner_instance_id

    targets: list[str] = []
    instance = params.get("persona_instance_id")
    if isinstance(instance, str) and instance.strip():
        targets.append(instance.strip())
    session = params.get("session_id")
    if isinstance(session, str) and session.strip():
        # A session whose owner cannot be derived is aimed at nobody this credential holds.
        targets.append(chat_session_owner_instance_id(session.strip()) or "")
    return targets


def channel_target_refusal(caller: Any, method: str, params: Any) -> CallAuthorization | None:
    """``None`` to proceed; the typed refusal when a channel call aims outside its binding.

    Runs at dispatch, after ``authorize_call`` admitted the verb, for every caller (a non-channel
    caller is answered ``None`` at once). ``runtime.channel.message`` resolves its own instance
    (the first bound one by default), so for it only a NAMED instance is checked here.
    """

    if not is_channel_caller(caller):
        return None
    if not external_access_on():
        return _refuse(
            REASON_EXTERNAL_ACCESS_OFF,
            "external agent access is off for this namespace; turn on \"Allow agent use outside the launcher\"",
            caller,
        )
    targets = _targets(method, params if isinstance(params, dict) else {})
    if method == CHANNEL_MESSAGE_METHOD and not targets:
        return None
    bound = set(getattr(caller, "bound_instances", ()) or ())
    if targets and all(target in bound for target in targets):
        return None
    return _refuse(
        REASON_CHANNEL_INSTANCE_NOT_BOUND,
        f"{method} must name a persona instance this channel credential is bound to",
        caller,
    )
