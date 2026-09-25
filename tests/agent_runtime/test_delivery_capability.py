"""The explicit async-delivery declaration (agent_runtime.delivery_capability).

Upstream's ``async_delivery_supported`` answers True for an unbound session; the
agent-chat dispatch lane must read that silence as a refusal. Each case runs in a
fresh ``contextvars.Context`` so the contextvar starts at upstream's ``_UNSET``.
"""

from __future__ import annotations

import contextvars


def _fresh(fn):
    return contextvars.Context().run(fn)


def test_silence_is_not_a_declaration():
    from agent_runtime.delivery_capability import async_delivery_declared
    from gateway.session_context import async_delivery_supported
    from tools.agent_chat_tool import _async_delivery_available

    assert _fresh(async_delivery_supported) is True  # upstream's default
    assert _fresh(async_delivery_declared) is False
    assert _fresh(_async_delivery_available) is False


def test_a_positive_declaration_grants_delivery():
    from agent_runtime.delivery_capability import async_delivery_declared, declare_async_delivery_channel
    from tools.agent_chat_tool import _async_delivery_available

    def declared():
        declare_async_delivery_channel()
        return async_delivery_declared(), _async_delivery_available()

    assert _fresh(declared) == (True, True)


def test_a_stateless_declaration_is_declared_but_refuses():
    from agent_runtime.delivery_capability import async_delivery_declared
    from gateway.session_context import declare_stateless_channel
    from tools.agent_chat_tool import _async_delivery_available

    def stateless():
        declare_stateless_channel()
        return async_delivery_declared(), _async_delivery_available()

    assert _fresh(stateless) == (True, False)
