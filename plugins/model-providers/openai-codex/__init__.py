"""OpenAI Codex (Responses API) provider profile."""

from providers import register_provider
from providers.base import ProviderProfile

class CodexProfile(ProviderProfile):
    """OpenAI Codex — declares the per-generation Responses ladder."""

    def supported_reasoning_efforts(self, model: str | None) -> tuple[str, ...]:
        """The Codex Responses vocabulary for *model* (``codex_supported_efforts``)."""
        from agent.reasoning_effort import codex_supported_efforts

        return codex_supported_efforts(model)


openai_codex = CodexProfile(
    name="openai-codex", aliases=("codex", "openai_codex"), api_mode="codex_responses",
    env_vars=(),  # OAuth external — no API key
    base_url="https://chatgpt.com/backend-api/codex", auth_type="oauth_external",
)

register_provider(openai_codex)
