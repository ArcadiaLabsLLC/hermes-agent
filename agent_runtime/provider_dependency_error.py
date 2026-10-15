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
