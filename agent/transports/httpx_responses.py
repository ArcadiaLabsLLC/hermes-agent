"""The ``codex_responses`` wire without the ``openai`` SDK: ``client.responses.create`` over raw ``httpx``.

Upstream's Codex runtime (``agent.codex_runtime.run_codex_stream``) and the auxiliary
Codex adapter call ``responses.create(stream=True)`` and assemble the final response
themselves from the typed events; a non-streamed call gets the typed ``Response``.
This resource is that one method on :class:`~agent.transports.httpx_client.SdkFreeClient`
— the same client family as the chat-completions wire, as the ``openai`` SDK is one
client for both — so nothing above it changes. Recovered from the July mobile core's
raw Responses lane (``mobile_core/src/hermes_mobile_core/turn_runner.py`` at
``a4ce2c42c89``), which assembled its own turn; this one returns the SDK's objects
and leaves the assembling to the loop that already does it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.transports import sdk_shapes

if TYPE_CHECKING:
    from agent.transports.httpx_client import SdkFreeClient

__all__ = ["ResponsesResource"]


class ResponsesResource:
    """``openai.OpenAI().responses``: ``create(**kwargs)`` -> ``Response`` or a stream of events."""

    def __init__(self, client: "SdkFreeClient") -> None:
        self._client = client

    def create(self, *, stream: bool = False, **kwargs: Any) -> Any:
        targets = (sdk_shapes.ROOTS["responses.response"], sdk_shapes.ROOTS["responses.event"])
        return self._client.post("/responses", stream=stream, targets=targets, **kwargs)
