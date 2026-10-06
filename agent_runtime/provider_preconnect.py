"""Open the provider connection on the prewarm thread, not on the first turn.

h-turn1 A4 (``docs/agent-runtime-harness/planned/turn-latency-h-turn1-2026-10-05.md``).
A resident actor's OpenAI client rides upstream's process-shared keepalive
transport (``agent/process_bootstrap.py::build_keepalive_http_client``), so a
chat's first turn opens a connection. The FIRST one in the process pays the
resolver, the first full TLS handshake and the certificate chain (262-1,454 ms
on record, every later one 21-56 ms). One ``HEAD`` to the provider's base URL
through the actor's OWN transport, right after the prewarm built it, moves that
first-in-process cost here.

The request carries the actor's IDENTITY headers (``User-Agent``, ``originator``
-- :data:`IDENTITY_HEADERS`) and nothing else. A bare ``HEAD`` is what the edge
in front of ``chatgpt.com`` challenges: it answered ``403`` with
``cf-mitigated: challenge`` and ``Connection: close`` (probed 2026-10-05), so
httpcore dropped the connection it had just opened and turn 1 still handshook
(``request_built -> tls_done`` 712 ms on the 23:16Z Neko chat, 3 s after a
``status=403`` pre-connect). With the identity the edge passes the request to
the origin, which answers ``404 Connection: keep-alive`` and the connection
stays in the pool the turn's per-request client shares
(``agent/process_bootstrap.py::build_keepalive_http_client``). The receipt's
``kept`` says which happened.

h-conn-pool: the request goes through the client the TURN checks out, not
the actor's primary client. A codex / chat-completions turn sends on the
per-request client ``agent._create_request_openai_client`` caches; the pre-connect
builds that client and leaves it cached (released with a reuse reason), so the
connection it warms sits in the pool of the very ``httpx.Client`` the turn's
request rides -- one pool whether or not upstream's process-shared transport
applies (a proxy, a full transport cache and the SDK-free client without a
keep-alive client each give a client its own pool).

What it does not do: send a body, call a model, or carry a credential (the SDK
and the SDK-free client both add auth per request, never on the ``httpx.Client``,
and :data:`IDENTITY_HEADERS` admits no other header);
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

PRECONNECT_RECEIPT = "persona_chat_actor_prewarm_connect host=%s status=%s kept=%d elapsed_ms=%d"

#: The only headers the pre-connect copies from the actor's client: who is
#: calling, never on whose account. Lower-case names; matched case-insensitively.
IDENTITY_HEADERS = ("user-agent", "originator")

#: ``profile_timing`` key the prewarm writes when it opened a connection.
PREWARM_CONNECT_MS = "prewarm_connect_ms"

PRECONNECT_TIMEOUT_SECONDS = 3.0

STATUS_NO_CLIENT = "no_client"
STATUS_NO_URL = "no_base_url"
STATUS_LOOPBACK = "skipped_loopback"
STATUS_FAILED = "failed"


#: API modes whose turn sends on ``agent._create_request_openai_client``'s cached client.
REQUEST_CLIENT_API_MODES = frozenset({"codex_responses", "chat_completions"})


def _turn_client(agent: Any) -> Any:
    """The provider client the turn's request will go through.

    For :data:`REQUEST_CLIENT_API_MODES`, the per-request client, built here and
    released with a reuse reason so the turn's checkout finds it cached; any
    failure falls back to the primary ``agent.client``.
    """

    create = getattr(agent, "_create_request_openai_client", None)
    release = getattr(agent, "_close_request_openai_client", None)
    if str(getattr(agent, "api_mode", "") or "") in REQUEST_CLIENT_API_MODES and callable(create) and callable(release):
        try:
            client = create(reason="prewarm_preconnect")
            release(client, reason="request_complete")
            return client
        except Exception:
            logger.debug("prewarm pre-connect could not check out the request client", exc_info=True)
    return getattr(agent, "client", None)


def _http_client(agent: Any) -> Any:
    """The ``httpx.Client`` under the turn's provider client, or None.

    ``openai.OpenAI._client`` and ``SdkFreeClient._client`` (``agent/transports/
    httpx_client.HttpCore``) are both the client the turn's request goes through.
    """

    try:
        import httpx
    except Exception:
        return None
    http = getattr(_turn_client(agent), "_client", None)
    return http if isinstance(http, httpx.Client) else None


def _base_url(agent: Any) -> str:
    url = str(getattr(agent, "base_url", "") or "").strip()
    if not url:
        url = str(getattr(getattr(agent, "client", None), "base_url", "") or "").strip()
    return url


def _identity_headers(agent: Any) -> dict[str, str]:
    """The actor client's :data:`IDENTITY_HEADERS`, from the first source that has them.

    ``agent._client_kwargs["default_headers"]`` is what every client of the actor
    is built from (the turn's per-request client included); the SDK's own
    ``_custom_headers`` / the SDK-free ``_default_headers`` and the SDK's
    ``user_agent`` cover an actor built some other way.
    """

    client = getattr(agent, "client", None)
    kwargs = getattr(agent, "_client_kwargs", None)
    sources = (
        kwargs.get("default_headers") if isinstance(kwargs, dict) else None,
        getattr(client, "_custom_headers", None),
        getattr(client, "_default_headers", None),
    )
    headers: dict[str, str] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for name, value in source.items():
            key = str(name).lower()
            if key in IDENTITY_HEADERS and key not in headers and isinstance(value, str) and value:
                headers[key] = value
    user_agent = getattr(client, "user_agent", None)
    if "user-agent" not in headers and isinstance(user_agent, str) and user_agent:
        headers["user-agent"] = user_agent
    return headers


def _is_loopback(host: str) -> bool:
    if host in ("localhost", "") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def preopen_provider_connection(agent: Any, timing: dict[str, Any]) -> str:
    """One credential-free ``HEAD`` to ``agent``'s base URL, under the actor's identity. Returns a status.

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
    kept = 0
    try:
        response = http.request(
            "HEAD", url, headers=_identity_headers(agent), timeout=PRECONNECT_TIMEOUT_SECONDS,
        )
        status = str(response.status_code)
        kept = int(str(response.headers.get("connection", "")).strip().lower() != "close")
        response.close()
    except Exception:
        logger.debug("prewarm provider pre-connect failed for %s", host, exc_info=True)
        status = STATUS_FAILED
    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
    timing[PREWARM_CONNECT_MS] = elapsed_ms
    logger.info(PRECONNECT_RECEIPT, host, status, kept, elapsed_ms)
    return status


__all__ = [
    "IDENTITY_HEADERS",
    "REQUEST_CLIENT_API_MODES",
    "PRECONNECT_RECEIPT",
    "PREWARM_CONNECT_MS",
    "preopen_provider_connection",
]
