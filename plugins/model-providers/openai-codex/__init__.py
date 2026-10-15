"""OpenAI Codex (Responses API) provider profile."""

from providers import register_provider
from providers.base import ProviderProfile

class CodexProfile(ProviderProfile):
    def supported_reasoning_efforts(self, model, *, base_url=None):
        from hermes_cli.models_reasoning_caps import cached_control_efforts
        return cached_control_efforts(self.name, model, base_url=base_url)


openai_codex = CodexProfile(
    name="openai-codex", aliases=("codex", "openai_codex"), api_mode="codex_responses",
    env_vars=(),  # OAuth external — no API key
    base_url="https://chatgpt.com/backend-api/codex", auth_type="oauth_external",
)

register_provider(openai_codex)
