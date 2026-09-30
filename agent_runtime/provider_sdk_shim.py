"""The phone's ``openai`` package: the SDK-free client family bound under the SDK's own names.

A profile that ships no provider SDK (``agent.provider_sdks: false``, the bundled phone) has no
``openai`` to import, and upstream imports it by name at about a dozen sites — module-level
(``agent.auxiliary_wire``, ``agent.acp_openai_bridge``, ``agent.auxiliary_async_rebuild``) and
function-local (``agent.chat_completion_helpers``, ``agent.codex_runtime``, the mem0 LLM,
cloud STT, streaming TTS). Each of those used to carry its own ``except ImportError`` fallback
in upstream's file. This module retires them as a class: :func:`ensure_provider_sdk_shim`
registers one ``openai`` module in ``sys.modules`` whose names ARE the SDK-free classes of
:mod:`agent.transports.httpx_client`, so every upstream site keeps upstream's bytes and gets
the client the phone's chokepoints already build (``isinstance`` included).

Phone-only, never a shadow: it installs only when ``agent.provider_sdks`` is off AND no real
``openai`` is importable, and the phone's entry (``EmbeddedServe.start``) calls it beside the
loop placeholders, before any request can import the agent loop. The module carries no
``__spec__``, so ``importlib.util.find_spec("openai")`` raises and upstream's package probes
(``tools.tts_tool._package_installed``) still read "not installed".

What the SDK-free client does not speak (``audio``) raises ``SdkFreeWireUnavailable`` at the
attribute, the error the old per-site ``missing_sdk`` fallbacks raised at construction.
``anthropic`` is not shimmed: its one site is a builder branch (``anthropic_adapter._require_sdk``)
that already hands out ``SdkFreeAnthropicClient``.
"""

from __future__ import annotations

import importlib.util
import sys
import types

__layer__ = "lanes"

__all__ = ["SHIM_MARKER", "ensure_provider_sdk_shim", "is_shim", "stand_in_modules"]

#: Set on every module this installs, so a census can tell the shim from a real SDK.
SHIM_MARKER = "__hermes_sdk_shim__"

_TOOL_CALL_MODULE = "openai.types.chat.chat_completion_message_tool_call"


def is_shim(module: object) -> bool:
    return bool(getattr(module, SHIM_MARKER, False))


def _real_openai_importable() -> bool:
    if "openai" in sys.modules:
        return sys.modules["openai"] is not None
    try:
        return importlib.util.find_spec("openai") is not None
    except (ImportError, ValueError):
        return False


def _module(name: str, **names: object) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__spec__ = None
    setattr(module, SHIM_MARKER, True)
    for key, value in names.items():
        setattr(module, key, value)
    return module


def stand_in_modules() -> dict[str, types.ModuleType]:
    """The ``sys.modules`` entries the shim registers (the packaging closure asks these too)."""
    from agent.transports import httpx_client as sdk_free

    tool_call, function = sdk_free.chat_tool_call_factories()
    modules = {
        "openai": _module(
            "openai",
            OpenAI=sdk_free.SdkFreeClient,
            AsyncOpenAI=sdk_free.AsyncSdkFreeClient,
            APIError=sdk_free.APIError,
            APIStatusError=sdk_free.ProviderHTTPError,
            APIConnectionError=sdk_free.APIConnectionError,
            APITimeoutError=sdk_free.APITimeoutError,
        ),
        "openai.types": _module("openai.types"),
        "openai.types.chat": _module("openai.types.chat"),
        _TOOL_CALL_MODULE: _module(_TOOL_CALL_MODULE, ChatCompletionMessageToolCall=tool_call, Function=function),
    }
    modules["openai"].types = modules["openai.types"]
    modules["openai.types"].chat = modules["openai.types.chat"]
    modules["openai.types.chat"].chat_completion_message_tool_call = modules[_TOOL_CALL_MODULE]
    return modules


def ensure_provider_sdk_shim() -> bool:
    """Register the ``openai`` shim when this profile ships no SDK; True when it is in place."""
    if is_shim(sys.modules.get("openai")):
        return True
    from agent.transports.httpx_client import provider_sdks_enabled

    if provider_sdks_enabled() or _real_openai_importable():
        return False
    sys.modules.update(stand_in_modules())
    return True
