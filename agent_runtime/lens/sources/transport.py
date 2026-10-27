"""The HTTP read every Lens poll source shares: classified, bounded, never redirected.

Plan ``eternia-lens-in-hermes.md`` W10 (stage L1), ported in spirit from Companion's
``monitor_http_transport.dart``:

* the host is RESOLVED and every address classified before a byte is sent;
  loopback, private, link-local, multicast, reserved and unspecified addresses are
  refused unless the feed opted in (``allow_private_network``);
* a redirect is never followed (a 3xx is an ``unavailable`` read, so a redirect
  cannot walk a classified URL onto an unclassified one);
* the body is capped at :data:`MAXIMUM_BODY_BYTES` and the read at
  :data:`TIMEOUT_SECONDS`;
* a caller that holds :class:`Validators` (the poller, per ``http_json`` feed, in memory)
  sends ``If-None-Match`` / ``If-Modified-Since``; a ``304`` then answers
  ``not_modified`` and the caller replays the value it last read (plan
  ``LENS_EXTENSIONS_2026-10-27.md`` §2 decision 5). A validator never reaches the store;
* every read names its reader: ``User-Agent: EterniaLens/<version>`` (:data:`USER_AGENT`,
  plan ``LENS_EXTENSIONS_2026-10-27.md`` §2 decision 6).

A failed read answers a typed :class:`ReadReason` and the HTTP status — never the
body, a header or an exception message, so nothing a server says (an echoed
token, a stack trace) can reach the store.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable
from urllib.parse import urlsplit

from ... import __version__

__layer__ = "lanes"

USER_AGENT = f"EterniaLens/{__version__}"
MAXIMUM_BODY_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 10.0

Resolver = Callable[[str], list[str]]


class ReadReason(str, Enum):
    OK = "ok"
    HTTP_STATUS = "http_status"
    TIMEOUT = "timeout"
    NETWORK = "network"
    REDIRECT_REFUSED = "redirect_refused"
    TOO_LARGE = "too_large"
    NOT_JSON = "not_json"
    SELECTOR_MISSING = "selector_missing"
    NOT_A_NUMBER = "not_a_number"
    PRIVATE_ADDRESS_REFUSED = "private_address_refused"
    CREDENTIAL_MISSING = "credential_missing"
    NO_SERIES = "no_series"
    AMBIGUOUS_SERIES = "ambiguous_series"
    QUERY_FAILED = "query_failed"
    WATCHER_OFFLINE = "watcher_offline"
    #: The source answered, but the feed's value type or plausible range refused it (W2).
    TYPE_MISMATCH = "type_mismatch"
    IMPLAUSIBLE = "implausible"
    #: The feed's outlier guard refused the read (W2(c)).
    OUTLIER = "outlier"
    #: A total cost needed an exchange rate and held no current dated one (W5).
    FX_STALE = "fx_stale"
    #: A ``push`` feed is written by its ingress route only; nothing reads it (L3).
    PUSH_ONLY = "push_only"
    #: A POST to the feed's ingress route was refused (signature, replay, size, body; L3).
    INGRESS_REFUSED = "ingress_refused"
    #: A ``sql_readonly`` statement that does not begin with SELECT / WITH (L4).
    STATEMENT_REFUSED = "statement_refused"
    #: A ``command_allowlisted`` argv outside its allow list (L4).
    COMMAND_REFUSED = "command_refused"
    #: The command did not start, or exited non-zero (L4).
    COMMAND_FAILED = "command_failed"
    #: A command feed of a manifest that is not sealed (a preview of a draft; L4).
    NOT_SEALED = "not_sealed"
    SOURCE_FAILED = "source_failed"
    #: A conditional read's ``304``: the server asserted the last representation unchanged (W3).
    #: Not a gap — the poller records the feed's last value with this reason.
    NOT_MODIFIED = "not_modified"
    #: The host's shared read budget deferred a due read past the continuity limit (W3).
    HOST_BUDGET_DEFERRED = "host_budget_deferred"


@dataclass(frozen=True, slots=True)
class ReadResult:
    value: float | None
    reason: ReadReason
    http_status: int | None = None
    #: The answer's value-free skeleton (``lens.shapes``) when the source answered a document;
    #: kept off :meth:`to_json` — it is the poller's, for ``store_shapes``, never the preview's.
    shape: tuple[tuple[str, str], ...] | None = None

    @property
    def status(self) -> str:
        return "available" if self.value is not None else "unavailable"

    def to_json(self) -> dict[str, Any]:
        return {"status": self.status, "number": self.value, "reason": self.reason.value,
                "http_status": self.http_status}


#: The longest validator kept; a longer ``ETag`` / ``Last-Modified`` is not sent back.
MAXIMUM_VALIDATOR_BYTES = 256


@dataclass(slots=True)
class Validators:
    """One feed's conditional-read validators, held in memory by its poller (never stored),
    with ``answer`` — the read the source made of the document they name. Set together, so
    a ``304`` against them can only mean that read; a failed read in between moves neither."""

    etag: str | None = None
    last_modified: str | None = None
    answer: ReadResult | None = None

    def request_headers(self) -> dict[str, str]:
        sent = {"If-None-Match": self.etag, "If-Modified-Since": self.last_modified}
        return {name: value for name, value in sent.items() if value is not None}

    def remember(self, headers: Any) -> None:
        self.etag, self.last_modified = _validator(headers.get("etag")), _validator(headers.get("last-modified"))
        self.answer = None


def _validator(value: str | None) -> str | None:
    if value is None or not value.isascii() or not value.isprintable() or len(value) > MAXIMUM_VALIDATOR_BYTES:
        return None
    return value


def unavailable(reason: ReadReason, http_status: int | None = None) -> ReadResult:
    return ReadResult(value=None, reason=reason, http_status=http_status)


def system_resolver(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


def address_allowed(url: str, *, allow_private: bool, resolver: Resolver) -> ReadReason | None:
    """None when the URL's host may be read; else the refusal."""

    host = urlsplit(url).hostname or ""
    try:
        addresses = [host] if _is_ip(host) else resolver(host)
    except OSError:
        return ReadReason.NETWORK
    if not addresses:
        return ReadReason.NETWORK
    if allow_private or all(_public(a) for a in addresses):
        return None
    return ReadReason.PRIVATE_ADDRESS_REFUSED


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def fetch_json(url: str, *, headers: dict[str, str], params: dict[str, str] | None = None,
               allow_private: bool, client: Any = None, resolver: Resolver | None = None,
               validators: Validators | None = None) -> tuple[Any, ReadResult | None]:
    """``(document, None)`` on a 2xx JSON body, else ``(None, the failed read)``.

    With ``validators``: they are sent, a ``304`` answers ``not_modified``, and a 2xx JSON
    body replaces them with the response's own."""

    import httpx

    refusal = address_allowed(url, allow_private=allow_private, resolver=resolver or system_resolver)
    if refusal is not None:
        return None, unavailable(refusal)
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    conditional = {} if validators is None else validators.request_headers()
    try:
        with client.stream("GET", url, headers={**headers, **conditional, "User-Agent": USER_AGENT},
                           params=params) as response:
            if conditional and response.status_code == 304:
                return None, unavailable(ReadReason.NOT_MODIFIED, 304)
            if 300 <= response.status_code < 400:
                return None, unavailable(ReadReason.REDIRECT_REFUSED, response.status_code)
            if not 200 <= response.status_code < 300:
                return None, unavailable(ReadReason.HTTP_STATUS, response.status_code)
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAXIMUM_BODY_BYTES:
                    return None, unavailable(ReadReason.TOO_LARGE, response.status_code)
            status, answered = response.status_code, response.headers
    except httpx.TimeoutException:
        return None, unavailable(ReadReason.TIMEOUT)
    except httpx.HTTPError:
        return None, unavailable(ReadReason.NETWORK)
    finally:
        if owned:
            client.close()
    try:
        document = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, unavailable(ReadReason.NOT_JSON, status)
    if validators is not None:
        validators.remember(answered)
    return document, None
