"""The LAN gateway's listen pair and its "Allow access" flag — the narrow writes of the harness keys Eternia sets.

``plugins.entries.eternia-harness.settings.remote_gateway_listen`` (an IP address
literal to listen on, or ``false`` for off) and ``.remote_gateway_port`` (1-65535),
and nothing else. Eternia used to write them with two cold ``hermes config set``
children; ``runtime.gateway.listen.set`` is the typed call on the running Hermes
(row ``RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES``). It is
deliberately NOT a general config write: a ``config.set`` over RPC would let any
console caller write any key (review w1118a.69).

The write is upstream's ``save_config`` over the RAW user config (no defaults
dumped back), under its own lock, refusing a managed install. A new listen value
takes effect when the serve respawns — the caller's reconcile does that, as it
did after the argv write.

``remote_gateway_access`` (``gateway_access.ACCESS_KEY``: ``true`` / ``false``, absent = allowed) is the
third key, written by :func:`set_gateway_access` for ``runtime.gateway.access.set``. Unlike the listen
pair it needs no respawn: ``call_authorization`` reads it on every call from a device or peer.

Layer ``lanes``: it reads and writes ``hermes_cli.config`` at call time.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from typing import Any

from .gateway_access import ACCESS_KEY, gateway_access_allowed
from .harness_settings import SETTINGS_PATH

__layer__ = "lanes"
__all__ = [
    "ACCESS_KEY", "GatewayListenRefused", "GatewayListenReason", "LISTEN_KEY", "PORT_KEY", "set_gateway_access",
    "set_gateway_listen",
]

LISTEN_KEY = "remote_gateway_listen"
PORT_KEY = "remote_gateway_port"


class GatewayListenReason(StrEnum):
    INVALID = "invalid_request"
    MANAGED = "config_managed"
    UNREADABLE = "config_unreadable"
    WRITE_FAILED = "config_write_failed"


class GatewayListenRefused(ValueError):
    def __init__(self, reason: GatewayListenReason, field: str | None = None):
        super().__init__(reason.value)
        self.reason = reason
        self.field = field


def _listen_value(listen: Any) -> str | bool:
    """``False`` (off) or a canonical IP address literal; anything else is refused.

    An address literal, not a hostname: the listener binds it, and a name would
    resolve at bind time to something the operator never saw."""
    if listen is False:
        # MUTATION: answer ``None`` and test_off_is_written_as_false_and_stays reddens (hermes reads
        # ``false`` as "no listener"; a cleared key would leave the default, not state the decision).
        return False
    if isinstance(listen, str):
        try:
            return str(ipaddress.ip_address(listen.strip()))
        except ValueError:
            pass
    raise GatewayListenRefused(GatewayListenReason.INVALID, "listen")


def _port_value(port: Any) -> int:
    if type(port) is not int or not 1 <= port <= 65535:
        raise GatewayListenRefused(GatewayListenReason.INVALID, "port")
    return port


def _write_settings(values: dict[str, Any], keys: tuple[str, ...]) -> tuple[dict, dict]:
    """Write *values* into the harness settings of the RAW user config; ``(before, after)`` of *keys*.

    Saved only when a value changed. A managed install, an unreadable file and a failed save are refused."""
    from hermes_cli.config import is_managed, read_user_config_raw, save_config

    if is_managed():
        raise GatewayListenRefused(GatewayListenReason.MANAGED)
    try:
        config = read_user_config_raw()
    except Exception:  # an unreadable file is refused, never read as empty
        raise GatewayListenRefused(GatewayListenReason.UNREADABLE) from None
    if not isinstance(config, dict):
        raise GatewayListenRefused(GatewayListenReason.UNREADABLE)
    node: dict = config
    for segment in SETTINGS_PATH:
        child = node.get(segment)
        if not isinstance(child, dict):
            child = {}
            node[segment] = child
        node = child
    before = {key: node.get(key) for key in keys}
    node.update(values)
    after = {key: node.get(key) for key in keys}
    if before != after:
        try:
            # The plugin keys are not in DEFAULT_CONFIG, so ``strip_defaults`` never drops them.
            save_config(config)
        except Exception:
            raise GatewayListenRefused(GatewayListenReason.WRITE_FAILED) from None
    return before, after


def set_gateway_listen(*, listen: Any, port: Any = None) -> dict:
    """Write the listen pair; ``port`` ``None`` leaves the stored port alone.

    Returns ``{listen, port, changed}``: what the two keys hold after the call
    (``port`` ``None`` when it was never set) and whether this call wrote.
    """
    values: dict[str, Any] = {LISTEN_KEY: _listen_value(listen)}
    if port is not None:
        values[PORT_KEY] = _port_value(port)
    before, after = _write_settings(values, (LISTEN_KEY, PORT_KEY))
    return {"listen": after[LISTEN_KEY], "port": after[PORT_KEY], "changed": before != after}


def set_gateway_access(*, allow: Any) -> dict:
    """Write "Allow access": ``allow`` must be a bool. Returns ``{access, changed}``.

    ``changed`` is against what the running serve ANSWERED before (an absent key answered allowed),
    so writing ``true`` over an absent key saves the decision but changes no one's answer."""
    if type(allow) is not bool:
        raise GatewayListenRefused(GatewayListenReason.INVALID, "allow")
    was = gateway_access_allowed()
    _write_settings({ACCESS_KEY: allow}, (ACCESS_KEY,))
    return {"access": allow, "changed": was != allow}
