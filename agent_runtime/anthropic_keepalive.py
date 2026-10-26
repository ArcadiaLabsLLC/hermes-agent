"""The anthropic request client rides the process-shared keep-alive pool
(RT-ANTHROPIC-CONN-PER-TURN, 2026-10-25).

**What was measured.** Neko on anthropic ``claude-opus-5-5`` handshook on EVERY
turn (``tls_done_ms`` 31-157, ``conn=new``, ten timed turns 2026-10-25
22:39-22:43) while Dev on openai-codex reused its connection. The anthropic SDK
builds its own ``httpx.Client`` with ``DEFAULT_CONNECTION_LIMITS`` -- no
``keepalive_expiry``, so httpx's 5 s default -- and a pooled connection is
reaped five seconds after a turn. The OpenAI-wire clients mount upstream's
process-shared transport (``agent/process_bootstrap.py::build_keepalive_http_client``,
``keepalive_expiry=20``), which is what the pre-connect and the idle keeper
(:mod:`agent_runtime.provider_preconnect`, :mod:`agent_runtime.idle_turn_keeper`)
keep warm.

**What this does.** :func:`adopt_keepalive_http_client` swaps a freshly built
direct anthropic SDK client's own ``httpx.Client`` for one from
``build_keepalive_http_client`` -- exactly what passing ``http_client=`` at
construction does (the SDK then uses the client as given; it sends its timeout,
headers and auth per request). One fork seam calls it in
``agent/client_lifecycle.py::_create_request_anthropic_client``, before the
client is cached and traced.

**What it does not do.** Bedrock clients (their own signing transport), the
SDK-free client (``agent.provider_sdks: false``) and any client whose
``_client`` is not a plain SDK-built ``httpx.Client`` are left alone. Fail-open:
a failure leaves the SDK's own client in place, which is the old behaviour.
"""

from __future__ import annotations

import logging
from typing import Any

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: The SDK's public base URL, for a key that carries none.
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"

#: Marks a client this module already moved, so a second call is a no-op.
_ADOPTED_ATTR = "_hermes_keepalive_adopted"


def _is_sdk_anthropic_client(client: Any) -> bool:
    try:
        import anthropic
    except Exception:
        return False
    return isinstance(client, anthropic.Anthropic)


def adopt_keepalive_http_client(client: Any, key: Any) -> bool:
    """Move a direct anthropic SDK client onto the keep-alive pool. True when moved. Never raises.

    ``key`` is ``_request_anthropic_client_key``'s tuple: ``("direct", api_key,
    base_url, timeout, drop_1m)`` or ``("bedrock", region)``.
    """

    try:
        if not isinstance(key, tuple) or not key or key[0] != "direct":
            return False
        if getattr(client, _ADOPTED_ATTR, False) or not _is_sdk_anthropic_client(client):
            return False
        import httpx

        own = getattr(client, "_client", None)
        if not isinstance(own, httpx.Client):
            return False
        base_url = str(key[2] or "").strip() if len(key) > 2 else ""
        from agent.process_bootstrap import build_keepalive_http_client

        shared = build_keepalive_http_client(base_url or ANTHROPIC_DEFAULT_BASE_URL)
        if shared is None:
            return False
        client._client = shared
        setattr(client, _ADOPTED_ATTR, True)
        try:
            own.close()  # never used: built by the SDK's constructor a moment ago
        except Exception:
            logger.debug("anthropic SDK's own http client close failed", exc_info=True)
        return True
    except Exception:
        logger.debug("anthropic keep-alive adoption skipped", exc_info=True)
        return False


__all__ = ["ANTHROPIC_DEFAULT_BASE_URL", "adopt_keepalive_http_client"]
