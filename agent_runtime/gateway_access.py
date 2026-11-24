"""This install's "Allow access" fact — whether your paired devices may USE it, read at call time.

Hermes row ``RT-ACCOUNT-ONLY-A-COMPUTER-WITH-ALLOW-ACCESS-OFF-STAYS-REACHABLE-BUT-LETS-NONE-OF-YOUR-DEVICES-USE-IT``
(owner 2026-11-23: "discovery and allowing pairing are different things though"). Eternia decides; hermes
holds ONE flag, ``plugins.entries.eternia-harness.settings.remote_gateway_access``, written only by the
local-console verb ``runtime.gateway.access.set`` (``gateway_listen_setting.set_gateway_access``).

* **Absent reads allowed.** Until this key the only off was closing the listener, so a config that never
  named it states no refusal. ``false`` is off; any other stored value is off too (fail closed, never a
  guess at what a malformed value meant), and so is a config that cannot be read.
* **Read at CALL time, never cached here.** ``hermes_cli.config``'s own stat-keyed cache makes the read
  cheap, and a write takes effect on the running serve at its next call, with no respawn.
* **Off refuses use, not reach.** ``call_authorization.authorize_call``'s access arm refuses a ``device``
  or ``peer`` caller ``access_off`` outside ``ACCESS_OFF_ANSWERS``; the hello, the reverse-lane park and
  code redemption still run, so a phone's line to this computer and pairing keep working while off.

Layer ``models``: every layer may read it (``harness_settings`` is ``models``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .harness_settings import harness_setting

__layer__ = "models"

__all__ = ["ACCESS_KEY", "REASON_ACCESS_OFF", "drop_remote_callers", "gateway_access_allowed", "is_remote_user"]

ACCESS_KEY = "remote_gateway_access"
#: The typed refusal. CONTRACT, not prose: Eternia branches on ``data.reason``.
REASON_ACCESS_OFF = "access_off"
_ABSENT = object()


def gateway_access_allowed(*, config: Mapping | None = None) -> bool:
    """True when the key is absent or ``true``; anything else is off. Never raises."""

    try:
        value = harness_setting(ACCESS_KEY, _ABSENT, config=config)
    except Exception:  # an unreadable config is access OFF, never on
        return False
    # MUTATION: answer ``value is True`` and test_an_absent_key_answers_a_device_as_today reddens.
    return value is _ABSENT or value is True


def is_remote_user(caller: Any) -> bool:
    """Is *caller* one of your devices or installs that "Allow access" governs — a paired ``device``
    of either kind (a screen or the owner's own bot channel) or a paired ``peer``?

    Console kinds are this machine's owner; a ``computer`` caller is on a PHONE, whose access is its
    grants (``reverse_lane.grants``); an unplaced caller is refused every verb already."""

    from .call_authorization import CALLER_DEVICE, CALLER_PEER

    return getattr(caller, "kind", None) in (CALLER_DEVICE, CALLER_PEER)


def drop_remote_callers(servers: tuple[Any, ...], *, reason: str) -> int:
    """Close every open device, peer and channel connection on *servers*; the count closed.

    A parked or attached reverse lane is not in a listener's connection table (the hello hook TOOK its
    socket, ``serve_socket.handshake``), so it stays: a phone's line survives every change. Each closed
    caller says hello again and reads the new ``access`` answer, and its subscriptions die with it."""

    from .call_authorization import caller_for_connection

    remote: Callable[[Any], bool] = lambda connection: is_remote_user(caller_for_connection(connection))
    return sum(server.drop_where(remote, reason=reason) for server in servers if server is not None)
