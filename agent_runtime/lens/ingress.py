"""The Lens PUSH DOOR: an in-serve HTTP listener for signed alert and JSON POSTs.

Plan ``p10-agent-2026-10-19.md`` §5.4 L3.3; owner ruling 2026-10-19 (§6 Q2): the
listener runs INSIDE ``harness serve`` (stdlib ``http.server``, nothing new in
``pyproject.toml``), not as a gateway platform adapter — the Launcher runs the
serve, never ``hermes gateway``.

Exposure (W11 a+b):

* bound to loopback (``127.0.0.1:47652``) unless the operator binds a LAN address
  through ``runtime.lens.ingress.bind`` (:func:`bind_ingress`: loopback or a private
  address only — never a public or unspecified one);
* bound ONLY while at least one route exists (:func:`sync_ingress`): the serve arms
  the door at boot and binds if routes are already stored; the first
  ``ingress.register`` binds it, the last ``ingress.revoke`` closes it. A serve whose
  home has no route (a test serve, a fresh install) never holds the port;
* ``POST /lens/<route_id>`` only; the body is capped at :data:`MAXIMUM_BODY_BYTES`
  and refused by its ``Content-Length`` BEFORE anything is read or verified;
* every route has its own secret (``ingress_routes``). Two signatures are accepted:
  ``X-Lens-Signature: sha256=<hex>`` = HMAC-SHA256(secret, ``"<ts>:" + body``) with
  ``X-Lens-Timestamp: <unix seconds>`` (Grafana's webhook HMAC with its timestamp
  header renamed), or Svix (``svix-id`` / ``svix-timestamp`` / ``svix-signature``,
  ``v1,<base64>`` over ``"<id>.<ts>." + body`` keyed by the secret's ``whsec_``
  payload). The timestamp must be within :data:`TIMESTAMP_WINDOW`; the id (Svix) or
  the signature (Lens) must not be in the ring of the last :data:`NONCE_RING` seen.
  The signature is verified first, so an unsigned caller can never fill the ring.

A refusal (``IngressRefusal``) is an HTTP 4xx with an EMPTY body — the status is
the only detail — and, for a route that exists, a gap row ``ingress_refused`` on
the route's feeds (at most one per route per :data:`REFUSAL_GAP_EVERY`, so an
unsigned flood cannot grow the store; W13). A refused POST never moves a rule.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import re
import threading
from collections import deque
from datetime import datetime, timedelta, UTC
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .ingress_mappings import IngressError, IngressRefusal, ingest
from .ingress_routes import ROUTE_PATH_PREFIX, SECRET_PREFIX, ingress_address, ingress_config_path, route_url
from .sources.transport import ReadReason
from .store import LensStore, LensStoreError
from .wire_value import WireError, WireRefusal, bounded_int

__layer__ = "lanes"

logger = logging.getLogger(__name__)

MAXIMUM_BODY_BYTES = 256 * 1024
TIMESTAMP_WINDOW = timedelta(minutes=5)
NONCE_RING = 1024
REFUSAL_GAP_EVERY = timedelta(minutes=1)
#: A slow sender holds one thread at most this long.
SOCKET_TIMEOUT_SECONDS = 10

_ROUTE_PATH = re.compile(re.escape(ROUTE_PATH_PREFIX) + r"([0-9a-f]{24})")

#: Refusal -> its HTTP status (the table; the body is always empty).
REFUSAL_STATUS: dict[IngressRefusal, int] = {
    IngressRefusal.UNKNOWN_ROUTE: 404,
    IngressRefusal.OVERSIZE: 413,
    IngressRefusal.BAD_SIGNATURE: 401,
    IngressRefusal.REPLAY: 409,
    IngressRefusal.BAD_BODY: 400,
    IngressRefusal.NOT_ENABLED: 409,
}
#: The refusals that leave a gap on the route's feeds (a route exists and was addressed).
_GAP_REFUSALS = frozenset({IngressRefusal.OVERSIZE, IngressRefusal.BAD_SIGNATURE, IngressRefusal.REPLAY,
                           IngressRefusal.BAD_BODY})


class _NonceRing:
    """The last ``size`` nonces, per listener (a restart clears it; the window bounds the rest)."""

    def __init__(self, size: int = NONCE_RING) -> None:
        self._order: deque = deque()
        self._seen: set = set()
        self._size = size
        self._lock = threading.Lock()

    def admit(self, nonce: tuple[str, str]) -> bool:
        """False when ``nonce`` was already seen; otherwise remember it."""

        with self._lock:
            if nonce in self._seen:
                return False
            self._order.append(nonce)
            self._seen.add(nonce)
            while len(self._order) > self._size:
                self._seen.discard(self._order.popleft())
            return True


def _header(headers: Any, name: str) -> str | None:
    value = headers.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _in_window(stamp: str | None, now: datetime) -> bool:
    if stamp is None or not stamp.isdigit():
        return False
    return abs(now - datetime.fromtimestamp(int(stamp), tz=UTC)) <= TIMESTAMP_WINDOW


def _svix_key(secret: str) -> bytes:
    return base64.b64decode(secret.removeprefix(SECRET_PREFIX))


def verify_signature(headers: Any, body: bytes, secret: str, now: datetime) -> tuple[IngressRefusal | None, str]:
    """``(refusal or None, nonce)`` for one POST. The signature is checked BEFORE the window."""

    svix_id = _header(headers, "svix-id")
    if svix_id is not None:
        stamp, offered = _header(headers, "svix-timestamp"), _header(headers, "svix-signature") or ""
        signed = f"{svix_id}.{stamp}.".encode() + body
        expected = base64.b64encode(hmac.new(_svix_key(secret), signed, hashlib.sha256).digest()).decode()
        candidates = [part.split(",", 1)[1] for part in offered.split() if part.startswith("v1,")]
        nonce = svix_id
    else:
        stamp, offered = _header(headers, "X-Lens-Timestamp"), _header(headers, "X-Lens-Signature") or ""
        signed = f"{stamp}:".encode() + body
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        candidates = [offered.removeprefix("sha256=").lower()] if offered else []
        nonce = candidates[0] if candidates else ""
    wanted = expected.encode("ascii")
    if stamp is None or not any(hmac.compare_digest(wanted, candidate.encode("utf-8", "replace"))
                                for candidate in candidates):
        return IngressRefusal.BAD_SIGNATURE, nonce
    if not _in_window(stamp, now):
        return IngressRefusal.REPLAY, nonce
    return None, nonce


def _route_feed_ids(route: dict[str, Any]) -> list[str]:
    mapping = route["mapping"]
    feeds = {mapping["feed_id"], *mapping["alerts"].values()} if "feed_id" in mapping else set(
        mapping["values"].values())
    return sorted(feeds)


class IngressListener:
    """The push door's HTTP server. ``start`` binds and serves on a daemon thread; ``stop`` closes it."""

    def __init__(self, host: str | None = None, port: int | None = None, *,
                 store_factory: Callable[[], LensStore] = LensStore,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        configured = ingress_address()
        self.host = configured[0] if host is None else host
        self.port = configured[1] if port is None else port
        self.store_factory, self.clock = store_factory, clock
        self.nonces = _NonceRing()
        self._last_gap: dict[str, datetime] = {}
        self._gap_lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None:
            return self.host, self.port
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> IngressListener:
        listener = self

        class _Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = False  # on Windows SO_REUSEADDR lets a second process take the port

            def handle_error(self, request: Any, client_address: Any) -> None:
                # A sender that stalls past the socket timeout is a log receipt, never a stderr traceback.
                logger.info("lens ingress request failed from %s", client_address[0], exc_info=True)

        class _Handler(BaseHTTPRequestHandler):
            server_version, sys_version, timeout = "lens", "", SOCKET_TIMEOUT_SECONDS

            def do_POST(self) -> None:
                self._answer(listener.handle(self.path, self.headers, self.rfile))

            def _not_allowed(self) -> None:
                self._answer(405)

            do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = _not_allowed

            def _answer(self, status: int) -> None:
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                logger.debug("lens ingress " + format, *args)

        self._server = _Server((self.host, self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="harness-serve-lens-ingress", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # --- one request ------------------------------------------------------------

    def handle(self, path: str, headers: Any, stream: Any) -> int:
        """The status for one POST (every refusal logged as a receipt with its reason, never the body)."""

        refusal, route = self._refusal(path, headers, stream)
        if refusal is None:
            return 202
        logger.info("lens ingress refused: route=%s reason=%s", None if route is None else route["route_id"],
                    refusal.value)
        if route is not None and refusal in _GAP_REFUSALS:
            self._refusal_gap(route)
        return REFUSAL_STATUS[refusal]

    def _refusal(self, path: str, headers: Any, stream: Any) -> tuple[IngressRefusal | None, dict | None]:
        from .credentials import resolve_credential

        matched = _ROUTE_PATH.fullmatch(path.split("?", 1)[0])
        store = self.store_factory()
        try:
            route = store.route(matched.group(1)) if matched else None
        except LensStoreError:
            route = None
        if route is None:
            return IngressRefusal.UNKNOWN_ROUTE, None
        length = _header(headers, "Content-Length")
        if _header(headers, "Transfer-Encoding") is not None or length is None or not length.isdigit():
            return IngressRefusal.BAD_BODY, route
        if int(length) > MAXIMUM_BODY_BYTES:
            return IngressRefusal.OVERSIZE, route
        body = stream.read(int(length))
        credential = resolve_credential(route["secret_ref"])
        if credential is None:
            return IngressRefusal.UNKNOWN_ROUTE, route
        now = self.clock()
        refusal, nonce = verify_signature(headers, body, credential.secret, now)
        if refusal is not None:
            return refusal, route
        if not self.nonces.admit((route["route_id"], nonce)):
            return IngressRefusal.REPLAY, route
        try:
            ingest(route, body, received=now, store=store)
        except IngressError as exc:
            return exc.code, route
        except LensStoreError:
            return IngressRefusal.UNKNOWN_ROUTE, route
        return None, route

    def _refusal_gap(self, route: dict[str, Any]) -> None:
        now = self.clock()
        with self._gap_lock:
            last = self._last_gap.get(route["route_id"])
            if last is not None and now - last < REFUSAL_GAP_EVERY:
                return
            self._last_gap[route["route_id"]] = now
        store = self.store_factory()
        for feed_id in _route_feed_ids(route):
            store.record(route["monitor_id"], feed_id, observed_at=now, received_at=now, value=None,
                         reason=ReadReason.INGRESS_REFUSED.value)


# --- the serve's one listener ------------------------------------------------------

#: ``armed``: a serve owns the door (set at boot, cleared with its liveness event);
#: ``listener``: the bound listener, present only while armed AND a route exists.
_ACTIVE: dict[str, Any] = {"listener": None, "armed": False}
_ACTIVE_LOCK = threading.Lock()


def active_listener() -> IngressListener | None:
    return _ACTIVE["listener"]


def sync_ingress(store: LensStore | None = None) -> IngressListener | None:
    """Bind the armed door while a route exists; close it when none does. The one writer of
    ``_ACTIVE["listener"]`` besides :func:`bind_ingress`'s move and the serve's stop.

    Called at boot (:func:`start_lens_ingress`) and after every route write
    (``ingress_routes.register_route`` / ``revoke_route``). Unarmed (no serve in this
    process) it does nothing. A bind failure is logged; the route write stands."""

    with _ACTIVE_LOCK:
        if not _ACTIVE["armed"]:
            return None
        wanted = bool((store or LensStore()).routes())
        current = _ACTIVE["listener"]
        if wanted and current is None:
            try:
                _ACTIVE["listener"] = IngressListener().start()
            except OSError:
                logger.warning("lens ingress did not bind %s:%s", *ingress_address(), exc_info=True)
        elif not wanted and current is not None:
            _ACTIVE["listener"] = None
            current.stop()
        return _ACTIVE["listener"]


def start_lens_ingress(*, stop_event: threading.Event) -> IngressListener | None:
    """Arm the push door for this serve and bind it if a route exists; it stops with
    ``stop_event``. None when not shipped, when no route exists yet (the first
    ``ingress.register`` binds it), or when the address cannot be bound (logged)."""

    from .poller import lens_shipped

    if not lens_shipped():
        return None
    with _ACTIVE_LOCK:
        _ACTIVE["armed"] = True

    def _stop_with_serve() -> None:
        stop_event.wait()
        with _ACTIVE_LOCK:
            current = _ACTIVE["listener"]
            _ACTIVE["listener"], _ACTIVE["armed"] = None, False
        if current is not None:
            current.stop()

    threading.Thread(target=_stop_with_serve, name="harness-serve-lens-ingress-stop", daemon=True).start()
    return sync_ingress()


def read_bind_host(value: Any) -> str:
    """A loopback or private address (W11 a): never a public, unspecified or multicast one."""

    try:
        address = ipaddress.ip_address(value if isinstance(value, str) else "")
    except ValueError:
        raise WireError(WireRefusal.INVALID_VALUE, "bind_host") from None
    if address.is_unspecified or address.is_multicast or not (address.is_loopback or address.is_private):
        raise WireError(WireRefusal.INVALID_VALUE, "bind_host_not_local")
    return str(address)


def bind_ingress(host: Any, port: Any) -> dict[str, Any]:
    """Write the home's bind and move a running listener to it. Returns the listener state."""

    from utils import atomic_json_write

    address = (read_bind_host(host), bounded_int(port, minimum=1024, maximum=65535))
    path = ingress_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, {"host": address[0], "port": address[1]}, indent=2, sort_keys=True)
    with _ACTIVE_LOCK:
        current = _ACTIVE["listener"]
        if current is not None:
            current.stop()
            moved = IngressListener(*address)
            try:
                _ACTIVE["listener"] = moved.start()
            except OSError:
                _ACTIVE["listener"] = None
                logger.warning("lens ingress did not bind %s:%s", *address, exc_info=True)
    return ingress_state()


def ingress_state() -> dict[str, Any]:
    listener = active_listener()
    host, port = listener.address if listener is not None else ingress_address()
    return {"host": host, "port": port, "listening": listener is not None,
            "url_base": route_url("", (host, port)), "maximum_body_bytes": MAXIMUM_BODY_BYTES}
