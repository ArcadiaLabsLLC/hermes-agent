"""The HTTP read every Lens poll source shares: classified, bounded, never redirected.

Plan ``eternia-lens-in-hermes.md`` W10 (stage L1), ported in spirit from Companion's
``monitor_http_transport.dart``:

* the host is RESOLVED and every address classified before a byte is sent;
  loopback, private, link-local, multicast, reserved and unspecified addresses are
  refused unless the feed opted in (``allow_private_network``);
* a redirect is never followed (a 3xx is an ``unavailable`` read, so a redirect
  cannot walk a classified URL onto an unclassified one);
* the body is capped at :data:`MAXIMUM_BODY_BYTES` and the read at
  :data:`TIMEOUT_SECONDS`.

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

__layer__ = "lanes"

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
    SOURCE_FAILED = "source_failed"


@dataclass(frozen=True, slots=True)
class ReadResult:
    value: float | None
    reason: ReadReason
    http_status: int | None = None

    @property
    def status(self) -> str:
        return "available" if self.value is not None else "unavailable"

    def to_json(self) -> dict[str, Any]:
        return {"status": self.status, "number": self.value, "reason": self.reason.value,
                "http_status": self.http_status}


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
               allow_private: bool, client: Any = None, resolver: Resolver | None = None
               ) -> tuple[Any, ReadResult | None]:
    """``(document, None)`` on a 2xx JSON body, else ``(None, the failed read)``."""

    import httpx

    refusal = address_allowed(url, allow_private=allow_private, resolver=resolver or system_resolver)
    if refusal is not None:
        return None, unavailable(refusal)
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    try:
        with client.stream("GET", url, headers=headers, params=params) as response:
            if 300 <= response.status_code < 400:
                return None, unavailable(ReadReason.REDIRECT_REFUSED, response.status_code)
            if not 200 <= response.status_code < 300:
                return None, unavailable(ReadReason.HTTP_STATUS, response.status_code)
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAXIMUM_BODY_BYTES:
                    return None, unavailable(ReadReason.TOO_LARGE, response.status_code)
            status = response.status_code
    except httpx.TimeoutException:
        return None, unavailable(ReadReason.TIMEOUT)
    except httpx.HTTPError:
        return None, unavailable(ReadReason.NETWORK)
    finally:
        if owned:
            client.close()
    try:
        return json.loads(bytes(body).decode("utf-8")), None
    except (UnicodeDecodeError, ValueError):
        return None, unavailable(ReadReason.NOT_JSON, status)
