"""Message hygiene at the resolved auxiliary client boundary."""

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:  # fork seam: a profile without provider SDKs (agent.provider_sdks: false)
    from agent.transports.httpx_client import NoProviderSdk as AsyncOpenAI, NoProviderSdk as OpenAI

from agent.transports.chat_completions import ChatCompletionsTransport
# Fork seam (embedded Hermes): the SDK-free clients speak the same Chat Completions wire.
from agent.transports.httpx_client import AsyncSdkFreeClient, SdkFreeClient


def prepare_chat_messages(client, kwargs: dict) -> dict:
    """Sanitize actual Chat Completions SDK requests, not native adapter replay.

    Auxiliary and MoA callers can retain a prepared request before the virtual
    transport sanitizes its copy. The resolved SDK client identifies the wire;
    native Messages/Responses adapters must retain their reasoning sidecars.
    """
    if not isinstance(client, (OpenAI, AsyncOpenAI, SdkFreeClient, AsyncSdkFreeClient)) or "messages" not in kwargs:
        return kwargs
    messages = ChatCompletionsTransport().convert_messages(
        kwargs["messages"], model=kwargs.get("model"), base_url=str(getattr(client, "base_url", "") or ""),
    )
    return {**kwargs, "messages": messages}
