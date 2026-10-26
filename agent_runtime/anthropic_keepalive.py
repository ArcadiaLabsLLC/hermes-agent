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

**The SDK client is built once per key per process (RT-ANTHROPIC-CLIENT-BUILT-PER-TURN,
2026-10-26).** Warm turns reused the connection but still paid ``client_built_ms`` 79-113
(Dev on openai-codex: 4): every new agent constructed ``anthropic.Anthropic`` -- whose
constructor builds its own ``httpx.Client`` and SSL context -- only for the swap above to
throw that client away. :func:`adopt_keepalive_http_client` records one TEMPLATE per
``_request_anthropic_client_key``, and :func:`pooled_anthropic_client` hands each later build
``template.copy(http_client=<a new keep-alive view>)``: the constructor with ``http_client`` given builds no client and no SSL
context (0.2 ms against ~30 ms idle, measured 2026-10-26). Each agent still owns its own
client object and its own ``httpx.Client`` view, so one agent's teardown ``close()`` cannot
close a stranger's; the template itself is never handed out.

**What it does not do.** Bedrock clients (their own signing transport), the
SDK-free client (``agent.provider_sdks: false``), an Entra ID bearer-provider key (a
callable credential: its ``httpx.Client`` carries the per-request auth hook, and swapping it
would send the placeholder token) and any client whose
``_client`` is not a plain SDK-built ``httpx.Client`` are left alone. Fail-open:
a failure leaves the SDK's own client in place, which is the old behaviour.
"""

from __future__ import annotations

import logging
import threading
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
        if not _poolable_key(key):
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
        _record_template(client, key)
        try:
            own.close()  # never used: built by the SDK's constructor a moment ago
        except Exception:
            logger.debug("anthropic SDK's own http client close failed", exc_info=True)
        return True
    except Exception:
        logger.debug("anthropic keep-alive adoption skipped", exc_info=True)
        return False


def _poolable_key(key: Any) -> bool:
    """A direct key with a STATIC string credential. A callable (Entra ID bearer provider)
    rides its own hook-carrying ``httpx.Client`` and is never moved."""

    return (isinstance(key, tuple) and len(key) > 1 and key[0] == "direct"
            and isinstance(key[1], str))


#: One adopted template per ``_request_anthropic_client_key``; bounded, oldest evicted.
_TEMPLATES: dict[tuple, Any] = {}
_TEMPLATES_LOCK = threading.Lock()
_MAX_TEMPLATES = 8


def _copy_onto_pool(source: Any, key: tuple) -> Any | None:
    """``source.copy`` onto a fresh keep-alive view: no SDK-built client, no SSL context. None on failure."""

    try:
        from agent.process_bootstrap import build_keepalive_http_client

        base_url = str(key[2] or "").strip() if len(key) > 2 else ""
        view = build_keepalive_http_client(base_url or ANTHROPIC_DEFAULT_BASE_URL)
        if view is None:
            return None
        copied = source.copy(http_client=view)
        setattr(copied, _ADOPTED_ATTR, True)
        return copied
    except Exception:
        logger.debug("anthropic template copy skipped", exc_info=True)
        return None


def pooled_anthropic_client(key: Any) -> Any | None:
    """A copy of this process's adopted template for ``key``, or None (build as usual). Never raises.

    The fork seam at the top of ``agent/client_lifecycle.py::_build_anthropic_client_for_key``
    returns it in place of a fresh SDK construction; the first build for a key is adopted by
    :func:`adopt_keepalive_http_client`, which records the template."""

    if not _poolable_key(key):
        return None
    with _TEMPLATES_LOCK:
        template = _TEMPLATES.get(key)
    return _copy_onto_pool(template, key) if template is not None else None


def _record_template(client: Any, key: tuple) -> None:
    fresh = _copy_onto_pool(client, key)
    if fresh is None:
        return
    with _TEMPLATES_LOCK:
        while len(_TEMPLATES) >= _MAX_TEMPLATES:
            _TEMPLATES.pop(next(iter(_TEMPLATES)))
        _TEMPLATES[key] = fresh


__all__ = ["ANTHROPIC_DEFAULT_BASE_URL", "adopt_keepalive_http_client", "pooled_anthropic_client"]
