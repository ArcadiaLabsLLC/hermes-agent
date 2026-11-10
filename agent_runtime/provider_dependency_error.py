"""The typed pre-token dependency refusal, below every layer that raises or reads it."""
from __future__ import annotations

from .models import AgentPersona

__layer__ = "models"


class ProviderDependencyError(ImportError):
    """A pre-token dependency refusal with structured operator remediation."""

    def __init__(self, message: str, *, persona: AgentPersona, issues: list[dict[str, str]]):
        super().__init__(message)
        self.reason = issues[0]["kind"]
        self.provider = getattr(persona, "provider", None)
        self.model = getattr(persona, "model", None)
        self.missing_packages = tuple(dict.fromkeys(issue["package"] for issue in issues))
        self.repair_hint = "\n".join(issue["summary"] for issue in issues)


#: The harness-authored refusal reason for a turn no tier names a model for.
MODEL_UNSET_REASON = "model_unset"


class ChatModelUnsetError(RuntimeError):
    """No tier of a chat turn's cascade (chat override, instance, persona, profile ``model.default``)
    names a model, so the request is refused before any provider is asked.

    RT-NO-MODEL-CHAT-SENDS-AND-404S: a Base chat whose profile set only a provider credential sent an
    EMPTY model id to anthropic and settled ``chat_turn_provider_refused`` on its 404. Pre-token, like
    :class:`ProviderDependencyError`, and settled the same terminal way; the remedy is choosing a model.
    """

    reason = MODEL_UNSET_REASON

    def __init__(self, *, provider: str | None):
        super().__init__(
            "no model is chosen for this chat, so the request was not sent; choose a model for this "
            "chat or agent (or set the profile's default with `hermes model`)"
        )
        self.provider = provider or None
