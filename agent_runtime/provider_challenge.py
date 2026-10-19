"""A provider 403 whose body is a Cloudflare challenge page: typed, and named by the path it guarded.

Upstream classifies such a 403 ``upstream_blocked`` and summarises the page by its ``<title>``;
OpenAI's challenge page has none, so the operator read "HTTP 403 — HTML error page (title not
found)" and nothing about WHERE the request went (2026-10-19, Neko on ``gpt-6-sol``). The page
names the challenged path itself (``cUPMDTk:"/backend-api/codex/v1/messages?…"``), and a path's
wire disagreeing with the provider's own ``api_mode`` is a transport mismatch on our side, not a
firewall on theirs (runtime-queue RT-CONV-MODEL-SELECT-STALE-API-MODE).

Registered by the eternia-harness plugin on upstream's ``transform_api_error_classification``
hook; the verdict keeps upstream's ``upstream_blocked`` recovery (no retry, fallback) and carries
the typed reason and the one-line message on ``error_context``, which
``agent/provider_failure.py::attach_provider_failure`` puts on the turn's ``provider_error`` block.
"""
from __future__ import annotations

import logging
import re

__layer__ = "stores"
logger = logging.getLogger(__name__)

CHALLENGE_RECEIPT = ("provider_challenge_refusal provider=%s model=%s path=%s path_wire=%s "
                     "provider_api_mode=%s reason=%s")

TRANSPORT_MISMATCH = "transport_mismatch"
UPSTREAM_BLOCKED = "upstream_blocked"

#: Markers only a Cloudflare challenge/interstitial page carries (a subset of upstream's
#: ``_UPSTREAM_BLOCKED_PATTERNS``: the ones that say "challenge", not merely "blocked").
_CHALLENGE_MARKERS = ("__cf_chl", "cdn-cgi/challenge-platform", "cf-browser-verification",
                      "enable javascript and cookies to continue")
_CHALLENGE_PATH = re.compile(r'cUPMDTk\s*:\s*"([^"?]+)', re.IGNORECASE)
#: A request path's suffix -> the wire that speaks it.
_PATH_WIRES = (("/chat/completions", "chat_completions"), ("/messages", "anthropic_messages"),
               ("/responses", "codex_responses"))


def path_wire(path: str | None) -> str | None:
    trimmed = (path or "").rstrip("/")
    return next((wire for suffix, wire in _PATH_WIRES if trimmed.endswith(suffix)), None)


def _request_path(error) -> str | None:
    """The path the SDK actually requested (``error.request`` or ``error.response.request``)."""
    for holder in (error, getattr(error, "response", None)):
        try:
            url = getattr(getattr(holder, "request", None), "url", None)
        except Exception:  # httpx.Response.request raises when the response was built bare
            continue
        path = getattr(url, "path", None)
        if isinstance(path, str) and path:
            return path
    return None


def challenge_refusal(*, provider: str | None, model: str | None, status_code: int | None,
                      text: str, error=None) -> dict | None:
    """``{"reason", "message", "path"}`` for a 403 challenge page, else ``None``."""
    if status_code != 403 or not any(marker in text.lower() for marker in _CHALLENGE_MARKERS):
        return None
    match = _CHALLENGE_PATH.search(text)
    path = match.group(1) if match else _request_path(error)
    wire = path_wire(path)
    from agent_runtime.model_api_mode import selected_api_mode

    expected = selected_api_mode(provider, model) if provider else None
    reason = TRANSPORT_MISMATCH if wire and expected and wire != expected else UPSTREAM_BLOCKED
    message = f"HTTP 403 — Cloudflare challenge on {path or '(path not reported)'}"
    if reason == TRANSPORT_MISMATCH:
        message += f": {wire} sent to {provider}, which speaks {expected}"
    logger.warning(CHALLENGE_RECEIPT, provider or "-", model or "-", path or "-", wire or "-",
                   expected or "-", reason)
    return {"reason": reason, "message": message, "path": path}


def classify_challenge_refusal(*, provider: str = "", model: str = "", status_code=None,
                               error_message: str = "", error=None, **_kwargs) -> dict | None:
    """``transform_api_error_classification`` callback: decline (``None``) unless the 403 is a
    challenge page."""
    refusal = challenge_refusal(provider=provider, model=model, status_code=status_code,
                                text=f"{error if error is not None else ''}\n{error_message or ''}",
                                error=error)
    if refusal is None:
        return None
    return {"reason": UPSTREAM_BLOCKED, "retryable": False, "should_fallback": True,
            "message": refusal["message"],
            "error_context": {"reason": refusal["reason"], "message": refusal["message"]}}
