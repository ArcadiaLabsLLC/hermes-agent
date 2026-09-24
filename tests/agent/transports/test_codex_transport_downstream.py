"""Fork-owned half of ``tests/agent/transports/test_codex_transport.py``.

The fork's persona header-cache scope (``agent_runtime.cache_routing``: the
content-addressed ``prompt_cache_key``, session headers and
``_last_cache_routing_observability``) and the kwargs cases upstream no longer
carries. The ``transport`` fixture is upstream's, imported by name.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.chat_completion_helpers import build_api_kwargs
from tests.agent.transports.test_codex_transport import (  # noqa: F401 — upstream names the moved tests use
    transport,
)


class TestCodexBuildKwargs:

    def test_build_api_kwargs_copies_final_cache_routing_to_agent(self, transport):
        agent = SimpleNamespace(
            tools=[],
            api_mode="codex_responses",
            provider="openai-codex",
            base_url="https://chatgpt.com/backend-api/codex/responses",
            _base_url_hostname="chatgpt.com",
            _base_url_lower="https://chatgpt.com/backend-api/codex/responses",
            model="gpt-5.4",
            reasoning_config=None,
            session_id=None,
            cache_scope_id="private-conversation-alpha",
            max_tokens=None,
            request_overrides=None,
            _get_transport=lambda: transport,
            _prepare_messages_for_non_vision_model=lambda messages: messages,
            _resolved_api_call_timeout=lambda: None,
            _github_models_reasoning_extra_body=lambda: None,
            _codex_reasoning_replay_enabled=True,
        )

        build_api_kwargs(agent, [{"role": "user", "content": "Hi"}])

        routing = agent._last_cache_routing_observability
        assert routing["backend"] == "openai_codex"
        assert routing["cache_scope_source"] == "cache_scope_id"
        assert routing["session_header_fingerprint"].startswith("sha256:")
        assert "private-conversation-alpha" not in json.dumps(routing)

    def test_basic_kwargs(self, transport):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
        )
        assert kw["model"] == "gpt-5.4"
        assert kw["instructions"] == "You are helpful."
        assert "input" in kw
        assert kw["store"] is False

    def test_cache_routing_observability_fingerprints_final_request(self, transport):
        """Same static prefix stays comparable while conversation scope moves.

        The evidence is captured from final kwargs and must never retain the raw
        persona-chat scope/header values it is meant to diagnose.
        """
        messages = [
            {"role": "system", "content": "stable"},
            {"role": "user", "content": "Hi"},
        ]

        transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            header_cache_scope_id="private-conversation-alpha",
            is_codex_backend=True,
        )
        first = dict(transport._last_cache_routing_observability)
        transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            header_cache_scope_id="private-conversation-beta",
            is_codex_backend=True,
        )
        second = dict(transport._last_cache_routing_observability)

        assert first["prompt_cache_key_source"] == "static_prefix"
        assert first["prompt_cache_key_fingerprint"].startswith("sha256:")
        assert (
            first["prompt_cache_key_fingerprint"]
            == second["prompt_cache_key_fingerprint"]
        )
        assert first["cache_scope_source"] == "cache_scope_id"
        assert (
            first["session_header_fingerprint"]
            != second["session_header_fingerprint"]
        )
        assert (
            first["session_header_fingerprint"]
            == first["client_request_header_fingerprint"]
        )
        assert first["scope_headers_match"] is True
        assert first["raw_values_omitted"] is True
        encoded = json.dumps([first, second], sort_keys=True)
        assert "private-conversation-alpha" not in encoded
        assert "private-conversation-beta" not in encoded

    def test_non_codex_responses_preserves_caller_extra_headers(self, transport):
        messages = [{"role": "user", "content": "Hi"}]

        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            is_codex_backend=False,
            request_overrides={"extra_headers": {"x-test": "1"}},
        )

        assert kw["extra_headers"] == {"x-test": "1"}

    def test_codex_scope_set_session_none_emits_scope_headers(self, transport):
        """Persona-chat shape: session_id=None but a stable header_cache_scope_id →
        cache-scope headers ARE emitted, carrying the scope value."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            session_id=None,
            header_cache_scope_id="chat-persona-123",
            is_codex_backend=True,
        )
        headers = kw.get("extra_headers", {})
        assert headers.get("session_id") == "chat-persona-123"
        assert headers.get("x-client-request-id") == "chat-persona-123"

    def test_codex_scope_takes_precedence_over_session(self, transport):
        """When both are present, header_cache_scope_id wins for the routing headers."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            session_id="run-session-abc",
            header_cache_scope_id="chat-persona-123",
            is_codex_backend=True,
        )
        headers = kw.get("extra_headers", {})
        assert headers.get("session_id") == "chat-persona-123"
        assert headers.get("x-client-request-id") == "chat-persona-123"

    def test_codex_session_used_when_scope_absent(self, transport):
        """No header_cache_scope_id → the headers fall back to session_id exactly as
        before (worker/mission-run lanes are unchanged)."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            session_id="run-session-abc",
            header_cache_scope_id=None,
            is_codex_backend=True,
        )
        headers = kw.get("extra_headers", {})
        assert headers.get("session_id") == "run-session-abc"
        assert headers.get("x-client-request-id") == kw["prompt_cache_key"]

    def test_codex_content_cache_header_without_scope_or_session(self, transport):
        """Neither present → no cache-scope headers (current behavior held)."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            session_id=None,
            header_cache_scope_id=None,
            is_codex_backend=True,
        )
        assert "session_id" not in kw.get("extra_headers", {})
        assert kw["extra_headers"]["x-client-request-id"] == kw["prompt_cache_key"]

    @pytest.mark.parametrize("scope_param", ["header_cache_scope_id", "session_id"])
    def test_codex_cache_scope_headers_bound_long_ids(self, transport, scope_param):
        """Cache-routing headers must satisfy the provider's 64-character
        limit whether their source is the persona-chat override or the normal
        session fallback. The live Alice operator-chat id is the regression
        case: it is 66 characters and was previously forwarded verbatim."""
        live_alice_scope = (
            "persona_chat_personainst_profile_alice_agent_0f044056_7b2f618f1998"
        )
        assert len(live_alice_scope) == 66

        common = dict(
            model="gpt-5.4",
            messages=[{"role": "system", "content": "You are Alice."}],
            tools=[],
            is_codex_backend=True,
        )
        first = transport.build_kwargs(**common, **{scope_param: live_alice_scope})
        repeated = transport.build_kwargs(**common, **{scope_param: live_alice_scope})
        without_scope = transport.build_kwargs(header_cache_scope_id="another-persona", **common)
        different = transport.build_kwargs(
            **common,
            **{scope_param: f"{live_alice_scope[:-1]}0"},
        )

        if scope_param == "session_id":
            # Upstream separates physical transcript identity from bounded cache routing.
            assert first["extra_headers"]["session_id"] == live_alice_scope
            assert first["extra_headers"]["x-client-request-id"] == first["prompt_cache_key"]
            assert len(first["extra_headers"]["x-client-request-id"]) <= 64
            return
        first_scope = first["extra_headers"]["session_id"]
        assert first_scope == first["extra_headers"]["x-client-request-id"]
        assert first_scope != live_alice_scope
        assert 0 < len(first_scope) <= 64
        assert repeated["extra_headers"]["session_id"] == first_scope
        assert different["extra_headers"]["session_id"] != first_scope
        # Header normalization must not alter the content-addressed body key.
        assert first["prompt_cache_key"] == without_scope["prompt_cache_key"]

    def test_codex_cache_scope_preserves_id_at_provider_limit(self, transport):
        """Existing cache buckets remain stable when an id already satisfies
        the provider contract, including the exact 64-character boundary."""
        boundary_scope = "s" * 64
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=[{"role": "user", "content": "Hi"}],
            tools=[],
            header_cache_scope_id=boundary_scope,
            is_codex_backend=True,
        )

        assert kw["extra_headers"]["session_id"] == boundary_scope
        assert kw["extra_headers"]["x-client-request-id"] == boundary_scope

    def test_header_cache_scope_id_is_header_only_not_transcript_or_cache_key(self, transport):
        """header_cache_scope_id must ONLY change the cache-scope headers — never the
        input items (transcript), instructions, prompt_cache_key body field, or
        anything session-load related. Build the SAME request with and without a
        scope and assert everything but extra_headers is byte-identical."""
        messages = [
            {"role": "system", "content": "You are Neko."},
            {"role": "user", "content": "status?"},
        ]
        common = dict(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            session_id=None,
            is_codex_backend=True,
        )
        without = transport.build_kwargs(header_cache_scope_id="another-persona", **common)
        with_scope = transport.build_kwargs(header_cache_scope_id="chat-persona-123", **common)

        # The scope only adds routing headers; the request body is untouched.
        assert with_scope["input"] == without["input"]
        assert with_scope["instructions"] == without["instructions"]
        assert with_scope.get("prompt_cache_key") == without.get("prompt_cache_key")
        # prompt_cache_key is the content-addressed hash, NOT the scope id.
        assert with_scope.get("prompt_cache_key", "").startswith("pck_")
        assert "chat-persona-123" not in with_scope.get("prompt_cache_key", "")
        # The ONLY difference is the added cache-scope headers.
        assert without["extra_headers"]["session_id"] == "another-persona"
        assert with_scope["extra_headers"]["session_id"] == "chat-persona-123"

    def test_header_cache_scope_id_ignored_off_codex_backend(self, transport):
        """The scope headers are codex-backend-only. A non-codex responses call
        with a header_cache_scope_id must NOT sprout session_id/x-client-request-id."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
            header_cache_scope_id="chat-persona-123",
            is_codex_backend=False,
        )
        headers = kw.get("extra_headers", {})
        assert "session_id" not in headers
        assert "x-client-request-id" not in headers

    def test_xai_headers(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-3", messages=messages, tools=[],
            session_id="conv-123",
            is_xai_responses=True,
        )
        assert kw.get("extra_headers", {}).get("x-grok-conv-id") == "conv-123"
