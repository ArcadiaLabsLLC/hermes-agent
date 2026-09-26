"""Persona cache routing and redaction-safe request evidence."""
import hashlib
import json
from typing import Any, Dict, Optional, List

__layer__ = "stores"

def persona_content_cache_key(instructions: str, tools: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """Content-address the prompt cache key from the static request prefix.

    Returns ``pck_<sha256[:24]>`` of (instructions + sorted tool schemas), or
    None when there is nothing static to key on. The cache key is a routing
    hint only — never a correctness boundary — so two requests sharing a system
    prompt and tool set intentionally resolve to the same warm prefix bucket.

    The fix this exists for: recurring cron jobs build session_id as
    ``cron_<id>_<timestamp>``, so using session_id as the cache key made every
    fire cache-cold. The static prefix (identity + tools) is identical across
    fires, so hashing it gives a stable key that stays warm within the
    provider's cache TTL. Sorting tools by name keeps the hash insertion-order
    independent.
    """
    if not instructions and not tools:
        return None
    tools_part = ""
    if tools:
        sorted_tools = sorted(
            (t for t in tools if isinstance(t, dict)),
            key=lambda t: str(t.get("name") or t.get("type") or ""),
        )
        tools_part = json.dumps(
            sorted_tools, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    # \x00 separator so instructions ending in the tool JSON can't collide with
    # a request whose instructions contain that JSON and whose tools are empty.
    content = f"{instructions or ''}\x00{tools_part}"
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"pck_{digest}"

def _cache_routing_fingerprint(value: Any) -> str | None:
    """One-way fingerprint for a cache-routing value.

    Prompt observability must prove that two requests used the same effective
    routing identity without persisting the raw session/header value. Full
    SHA-256 keeps comparisons collision-resistant; the ``sha256:`` prefix makes
    the representation self-describing for Launcher/operator tooling.
    """

    text = str(value or "").strip()
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return f"sha256:{digest}"

def _cache_routing_observability(
    kwargs: Dict[str, Any],
    *,
    computed_cache_key: str | None,
    computed_cache_key_source: str,
    cache_scope_id: Any,
    session_id: Any,
    is_codex_backend: bool,
    is_github_responses: bool,
    is_xai_responses: bool,
) -> Dict[str, Any]:
    """Redaction-safe facts from the FINAL request kwargs.

    This is captured after request overrides and provider-specific routing have
    run, so it describes what the SDK will actually send rather than what an
    earlier caller intended. Raw cache keys, session ids, and header values are
    deliberately omitted.
    """

    extra_body = kwargs.get("extra_body")
    body_cache_key = kwargs.get("prompt_cache_key")
    if body_cache_key is None and isinstance(extra_body, dict):
        body_cache_key = extra_body.get("prompt_cache_key")
    if body_cache_key is None:
        key_source = "none"
    elif body_cache_key == computed_cache_key:
        key_source = computed_cache_key_source
    else:
        key_source = "request_override"

    headers = kwargs.get("extra_headers")
    headers = headers if isinstance(headers, dict) else {}
    session_header = headers.get("session_id")
    client_request_header = headers.get("x-client-request-id")
    scope_source = "none"
    if is_codex_backend and session_header is not None:
        scope_source = (
            "cache_scope_id"
            if str(cache_scope_id or "").strip()
            else "session_id"
            if str(session_id or "").strip()
            else "request_override"
        )
    backend = (
        "openai_codex"
        if is_codex_backend
        else "github_responses"
        if is_github_responses
        else "xai_responses"
        if is_xai_responses
        else "responses"
    )
    return {
        "schema_version": 1,
        "backend": backend,
        "prompt_cache_key_present": body_cache_key is not None,
        "prompt_cache_key_source": key_source,
        "prompt_cache_key_fingerprint": _cache_routing_fingerprint(body_cache_key),
        "cache_scope_source": scope_source,
        "session_header_present": session_header is not None,
        "session_header_fingerprint": _cache_routing_fingerprint(session_header),
        "client_request_header_present": client_request_header is not None,
        "client_request_header_fingerprint": _cache_routing_fingerprint(
            client_request_header
        ),
        "scope_headers_match": (
            session_header == client_request_header
            if session_header is not None and client_request_header is not None
            else None
        ),
        "raw_values_omitted": True,
    }


def apply_persona_cache_routing(
    request: Dict[str, Any],
    *,
    cache_scope_id: Any,
    session_id: Any,
    is_codex_backend: bool,
    is_github_responses: bool,
    is_xai_responses: bool,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """``(request, observability)`` for one FINAL Responses request (lane DOORS-A 2026-09-24).

    Runs as ``llm_request`` middleware on the kwargs upstream's
    ``ResponsesApiTransport.build_kwargs`` produced, so it overwrites the values IN PLACE
    wherever upstream put them (top-level ``prompt_cache_key``, xAI's ``extra_body`` copy,
    the Codex ``session_id`` / ``x-client-request-id`` headers) instead of re-deriving the
    placement. With a persona ``cache_scope_id``: the body key becomes the
    content-addressed :func:`persona_content_cache_key` (instructions + wire tools; the
    scope never enters it) and both Codex headers carry the bounded scope. Without one the
    request is untouched. Either way the observability block describes the final bytes.
    """

    from ._upstream_doors import (
        codex_bounded_prompt_cache_key as _bounded_prompt_cache_key,
        codex_cache_scope_from_session_id as _cache_scope_from_session_id,
        codex_content_cache_key as _content_cache_key,
    )

    req = dict(request)
    instructions = req.get("instructions")
    tools = req.get("tools")
    scope = str(cache_scope_id or "").strip()
    if scope:
        key = persona_content_cache_key(instructions, tools) or session_id
        bounded = _bounded_prompt_cache_key(key)
        if "prompt_cache_key" in req:
            if bounded:
                req["prompt_cache_key"] = bounded
            else:
                req.pop("prompt_cache_key", None)
        extra_body = req.get("extra_body")
        if isinstance(extra_body, dict) and "prompt_cache_key" in extra_body and bounded:
            req["extra_body"] = {**extra_body, "prompt_cache_key": bounded}
        if is_codex_backend:
            scoped = _bounded_prompt_cache_key(scope)
            existing = req.get("extra_headers")
            headers = dict(existing) if isinstance(existing, dict) else {}
            headers.update({"session_id": scoped, "x-client-request-id": scoped})
            req["extra_headers"] = headers
    else:
        upstream_scope = _cache_scope_from_session_id(session_id)
        key = _content_cache_key(instructions, tools, upstream_scope) or upstream_scope
    source = "static_prefix" if instructions or tools else "session_fallback" if key else "none"
    observability = _cache_routing_observability(
        req, computed_cache_key=_bounded_prompt_cache_key(key) or key,
        computed_cache_key_source=source, cache_scope_id=scope or None, session_id=session_id,
        is_codex_backend=is_codex_backend, is_github_responses=is_github_responses,
        is_xai_responses=is_xai_responses,
    )
    return req, observability


def route_persona_cache(request: Any, *, api_mode: Any = None, **_context: Any) -> Optional[Dict[str, Any]]:
    """The eternia-harness ``llm_request`` half for cache routing; None when not a persona
    Codex/Responses turn. Records the observability block on the bound agent."""

    if api_mode != "codex_responses" or not isinstance(request, dict):
        return None
    from agent_runtime.persona_turn_binding import current_persona_turn_agent

    agent = current_persona_turn_agent()
    if agent is None:
        return None
    from agent.codex_responses_adapter import classify_responses_route

    is_codex_backend, is_xai_responses, is_github_responses = classify_responses_route(agent)
    rewritten, observability = apply_persona_cache_routing(
        request, cache_scope_id=getattr(agent, "cache_scope_id", None),
        session_id=getattr(agent, "session_id", None), is_codex_backend=is_codex_backend,
        is_github_responses=is_github_responses, is_xai_responses=is_xai_responses,
    )
    agent._last_cache_routing_observability = observability
    return rewritten if rewritten != request else None
