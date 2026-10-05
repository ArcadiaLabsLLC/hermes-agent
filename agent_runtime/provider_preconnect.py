"""Open the provider connection on the prewarm thread, not on the first turn.

h-turn1 A4 (``docs/agent-runtime-harness/planned/turn-latency-h-turn1-2026-10-05.md``).
A resident actor's OpenAI client rides upstream's process-shared keepalive
transport (``agent/process_bootstrap.py::build_keepalive_http_client``), so a
chat's first turn opens a connection. The FIRST one in the process pays the
resolver, the first full TLS handshake and the certificate chain (262-1,454 ms
on record, every later one 21-56 ms). One ``HEAD`` to the provider's base URL
through the actor's OWN transport, right after the prewarm built it, moves that
first-in-process cost here.

What it does not do: send a body, call a model, or carry a credential (the SDK
and the SDK-free client both add auth per request, never on the ``httpx.Client``);
keep anything open beyond the transport's own ``keepalive_expiry`` (upstream's
value, unchanged by ruling A4-r1); touch a loopback provider (a local router has
no handshake worth moving). Fail-open: a refusal or a timeout is a receipt, never
an error, and the turn opens its own connection exactly as before.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from typing import Any
from urllib.parse import urlsplit

__layer__ = "policy"

logger = logging.getLogger(__name__)

PRECONNECT_RECEIPT = "persona_chat_actor_prewarm_connect host=%s status=%s elapsed_ms=%d"

#: ``profile_timing`` key the prewarm writes when it opened a connection.
PREWARM_CONNECT_MS = "prewarm_connect_ms"

PRECONNECT_TIMEOUT_SECONDS = 3.0

STATUS_NO_CLIENT = "no_client"
STATUS_NO_URL = "no_base_url"
STATUS_LOOPBACK = "skipped_loopback"
STATUS_FAILED = "failed"


def _http_client(agent: Any) -> Any:
    """The ``httpx.Client`` under the actor's provider client, or None.

    ``openai.OpenAI._client`` and ``SdkFreeClient._client`` (``agent/transports/
    httpx_client.HttpCore``) are both the client the turn's request goes through.
    """

    try:
        import httpx
    except Exception:
        return None
    http = getattr(getattr(agent, "client", None), "_client", None)
    return http if isinstance(http, httpx.Client) else None


def _base_url(agent: Any) -> str:
    url = str(getattr(agent, "base_url", "") or "").strip()
    if not url:
        url = str(getattr(getattr(agent, "client", None), "base_url", "") or "").strip()
    return url


def _is_loopback(host: str) -> bool:
    if host in ("localhost", "") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def preopen_provider_connection(agent: Any, timing: dict[str, Any]) -> str:
    """One credential-free ``HEAD`` to ``agent``'s base URL. Returns a status.

    The status is the response code as a string, or one of the ``STATUS_*``
    tokens. Writes :data:`PREWARM_CONNECT_MS` only when a request was sent.
    """

    http = _http_client(agent)
    if http is None:
        return STATUS_NO_CLIENT
    url = _base_url(agent)
    host = (urlsplit(url).hostname or "").lower()
    if not url or not host:
        return STATUS_NO_URL
    if _is_loopback(host):
        return STATUS_LOOPBACK
    started = time.perf_counter()
    try:
        response = http.request("HEAD", url, timeout=PRECONNECT_TIMEOUT_SECONDS)
        status = str(response.status_code)
        response.close()
    except Exception:
        logger.debug("prewarm provider pre-connect failed for %s", host, exc_info=True)
        status = STATUS_FAILED
    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
    timing[PREWARM_CONNECT_MS] = elapsed_ms
    logger.info(PRECONNECT_RECEIPT, host, status, elapsed_ms)
    return status


__all__ = [
    "PRECONNECT_RECEIPT",
    "PREWARM_CONNECT_MS",
    "preopen_provider_connection",
]
