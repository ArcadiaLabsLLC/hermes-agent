"""Lens push-door ROUTES: who may POST, into which monitor, and how the body maps.

Plan ``p10-agent-2026-10-19.md`` §5.4 L3.1. A route belongs to one SEALED monitor
and names how its body reads (``kind``: ``alertmanager`` | ``grafana`` |
``generic``) and which of the monitor's ``push`` feeds it may write (``mapping``).
It is the operator's own declaration: a route never writes a feed the sealed
manifest does not declare as ``push``, so the poller and a route never share a feed.

Mapping, by kind (canonical form; :func:`read_route_mapping`):

* ``alertmanager`` / ``grafana`` — ``{"feed_id": F, "alerts"?: {alertname: F'}}``:
  an alert named in ``alerts`` writes that feed, every other alert writes ``F``.
  Omitted, the monitor's ONE push feed is ``F`` (two or more is ``mapping_required``).
* ``generic`` — ``{"values": {"$.path": F, ...}, "observed_at"?: "$.path"}``: each
  selector (the poll door's bounded ``$.a.b[0]`` path) takes one number for its feed;
  ``observed_at`` names the source's time (epoch ms, or the canonical UTC string).

A route's AUTH mode (:class:`IngressAuth`, chosen at register, ``hmac`` by default)
says how a POST proves it holds the secret: ``hmac`` signs the body (Lens HMAC or
Svix), ``bearer`` (owner ruling 2026-10-19, ``RT-LENS-ALERTMANAGER-UNSIGNED``)
sends the route's SAME secret as ``Authorization: Bearer <secret>`` because
Alertmanager's ``webhook_config`` cannot sign a body. Bearer is the WEAKER mode — the
secret travels on every request — so it is taken only by :data:`BEARER_KINDS` and only
while the listener's bind is loopback or private (:func:`is_local_bind`), and the
wire marks such a route ``weaker: true``.

The SECRET is minted here, returned ONCE by :func:`register_route`, and stored in the
home's Lens credential file as ``ingress:<route_id>`` (``lens.credentials``); the
store row holds the reference only. Revoking a route forgets its secret.

The listener's address (``lens/ingress.json`` under the home, resolved at call
time) is loopback unless an operator bound it elsewhere (``runtime.lens.ingress.bind``,
stage L3.3); a route's ``url`` is built from it. The listener is bound only while a
route exists: every route write ends in ``ingress.sync_ingress``.
"""

from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime, UTC
from enum import Enum
from pathlib import Path
from typing import Any

from .feed import extraction_path, is_push_feed
from .store import LensStore, LensStoreError, StoreRefusal, to_ms
from .wire_value import WireError, WireRefusal, bounded_string, checked_object, enum_value, opaque_id

__layer__ = "lanes"

SECRET_PREFIX = "whsec_"
ROUTE_PATH_PREFIX = "/lens/"
DEFAULT_HOST = "127.0.0.1"
#: The listener's port when no bind was written (a fixed port, so a configured webhook survives a restart).
DEFAULT_PORT = 47652
#: The most feeds one generic route may write, and alert names one alert route may name.
MAXIMUM_MAPPED = 32


class IngressKind(str, Enum):
    ALERTMANAGER = "alertmanager"
    GRAFANA = "grafana"
    GENERIC = "generic"


ALERT_KINDS = frozenset({IngressKind.ALERTMANAGER, IngressKind.GRAFANA})


class IngressAuth(str, Enum):
    """How a POST to a route proves it holds the route's secret."""

    HMAC = "hmac"
    BEARER = "bearer"


#: The kinds that may take bearer auth (a sender that cannot sign a body); the rest keep HMAC.
BEARER_KINDS = frozenset({IngressKind.ALERTMANAGER})


def secret_ref_for(route_id: str) -> str:
    return f"ingress:{route_id}"


def ingress_config_path() -> Path:
    """``HERMES_HOME/lens/ingress.json`` — resolved at call time."""

    from hermes_constants import get_hermes_home

    return get_hermes_home() / "lens" / "ingress.json"


def ingress_address() -> tuple[str, int]:
    """``(host, port)`` the listener binds: the written bind, else loopback on :data:`DEFAULT_PORT`."""

    try:
        document = json.loads(ingress_config_path().read_text(encoding="utf-8"))
        return str(document["host"]), int(document["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_HOST, DEFAULT_PORT


def is_local_bind(host: str) -> bool:
    """True when ``host`` is a loopback or private address: the only bind ``ingress.bind`` writes
    and the only one a bearer route is accepted on. An unspecified (``0.0.0.0``), multicast,
    public or unparsable host is False."""

    import ipaddress

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not (address.is_unspecified or address.is_multicast) and (address.is_loopback or address.is_private)


def _read_auth(auth: Any, kind: IngressKind) -> IngressAuth:
    mode = IngressAuth.HMAC if auth is None else enum_value(auth, IngressAuth)
    if mode is IngressAuth.BEARER:
        if kind not in BEARER_KINDS:
            raise WireError(WireRefusal.INVALID_VALUE, "bearer_not_for_kind")
        if not is_local_bind(ingress_address()[0]):
            raise WireError(WireRefusal.INVALID_VALUE, "bearer_needs_local_bind")
    return mode


def route_url(route_id: str, address: tuple[str, int] | None = None) -> str:
    host, port = address or ingress_address()
    host = f"[{host}]" if ":" in host else host
    return f"http://{host}:{port}{ROUTE_PATH_PREFIX}{route_id}"


def _push_feeds(store: LensStore, monitor_id: str) -> list[str]:
    sealed = store.sealed(monitor_id)
    if sealed is None:
        raise LensStoreError(StoreRefusal.NOT_SEALED)
    return [feed["id"] for feed in sealed.manifest()["feeds"] if is_push_feed(feed)]


def _push_feed(value: Any, push_feeds: list[str]) -> str:
    feed_id = opaque_id(value)
    if feed_id not in push_feeds:
        raise WireError(WireRefusal.INVALID_VALUE, "not_a_push_feed")
    return feed_id


def read_route_mapping(kind: IngressKind, mapping: Any, push_feeds: list[str]) -> dict[str, Any]:
    """The canonical mapping for ``kind`` over the monitor's ``push_feeds``, or :class:`WireError`."""

    if kind in ALERT_KINDS:
        if mapping is None:
            if len(push_feeds) != 1:
                raise WireError(WireRefusal.INVALID_VALUE, "mapping_required")
            return {"feed_id": push_feeds[0], "alerts": {}}
        m = checked_object(mapping, {"feed_id"}, {"alerts"})
        alerts = m.get("alerts") or {}
        if not isinstance(alerts, dict) or len(alerts) > MAXIMUM_MAPPED:
            raise WireError(WireRefusal.INVALID_VALUE, "alerts")
        return {"feed_id": _push_feed(m["feed_id"], push_feeds),
                "alerts": {bounded_string(name, maximum=256): _push_feed(feed, push_feeds)
                           for name, feed in sorted(alerts.items())}}
    m = checked_object(mapping, {"values"}, {"observed_at"})
    values = m["values"]
    if not isinstance(values, dict) or not 1 <= len(values) <= MAXIMUM_MAPPED:
        raise WireError(WireRefusal.INVALID_VALUE, "values")
    out: dict[str, Any] = {"values": {extraction_path(path): _push_feed(feed, push_feeds)
                                      for path, feed in sorted(values.items())}}
    if m.get("observed_at") is not None:
        out["observed_at"] = extraction_path(m["observed_at"])
    return out


def register_route(monitor_id: str, kind: Any, mapping: Any = None, *, auth: Any = None,
                   store: LensStore | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Mint a route into ``monitor_id``'s push feeds. Returns ``{route_id, url, secret, ...}``;
    the secret is in this answer and nowhere else the wire can read. ``auth`` is
    ``hmac`` (default) or ``bearer`` (:func:`_read_auth`)."""

    from .credentials import set_credential

    store = store or LensStore()
    monitor_id = opaque_id(monitor_id)
    ingress_kind = enum_value(kind, IngressKind)
    mode = _read_auth(auth, ingress_kind)
    canonical = read_route_mapping(ingress_kind, mapping, _push_feeds(store, monitor_id))
    route_id = secrets.token_hex(12)
    secret = SECRET_PREFIX + base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    route = {"route_id": route_id, "monitor_id": monitor_id, "kind": ingress_kind.value,
             "secret_ref": secret_ref_for(route_id), "mapping": canonical, "auth": mode.value,
             "created_ms": to_ms(now or datetime.now(UTC))}
    set_credential(route["secret_ref"], scheme="bearer", secret=secret, now=now)
    try:
        store.save_route(route)
    except LensStoreError:
        _forget(route["secret_ref"])
        raise
    _sync_listener(store)
    return {**public_route(route), "secret": secret}


def _sync_listener(store: LensStore) -> None:
    from .ingress import sync_ingress

    sync_ingress(store)


def _forget(ref: str) -> None:
    from .credentials import forget_credential

    forget_credential(ref)


def public_route(route: dict[str, Any]) -> dict[str, Any]:
    """A route as the wire reads it: identity, kind, mapping, auth, url — never the secret.
    ``weaker`` is True for a bearer route (the Console labels it)."""

    return {"route_id": route["route_id"], "monitor_id": route["monitor_id"], "kind": route["kind"],
            "mapping": route["mapping"], "auth": route["auth"], "weaker": route["auth"] == IngressAuth.BEARER.value,
            "created_ms": route["created_ms"], "url": route_url(route["route_id"])}


def list_routes(monitor_id: str | None = None, *, store: LensStore | None = None) -> list[dict[str, Any]]:
    store = store or LensStore()
    return [public_route(row) for row in store.routes(monitor_id=None if monitor_id is None else opaque_id(monitor_id))]


def revoke_route(route_id: str, *, store: LensStore | None = None) -> dict[str, Any]:
    """Delete the route and forget its secret; a POST to it is ``unknown_route`` from now on."""

    store = store or LensStore()
    route = store.delete_route(opaque_id(route_id))
    _forget(route["secret_ref"])
    _sync_listener(store)
    return {**public_route(route), "revoked": True}
