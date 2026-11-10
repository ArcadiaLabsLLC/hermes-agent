"""Answer a provider read for ONE agent: under that agent's profile, the way its turn runs.

``runtime.provider.list`` and ``runtime.provider.usage`` answer for the serve's own home. A
client showing one agent's limits (Eternia's Usage & limits chip) names the agent instead
(``persona_instance_id``, or ``persona_id``); the read then runs inside the same
``resolve_persona_profile`` + ``persona_profile_context`` binding a turn of that agent runs in,
so it sees the accounts that turn would spend (RT-PROVIDER-USAGE-PER-AGENT-PROFILE).

No agent named -> no binding, the reply unchanged. An agent this runtime does not know is
refused ``agent_unknown``; one whose profile is missing, ``agent_profile_unavailable``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .provider_account import ProviderRefused

__layer__ = "stores"

__all__ = ["AgentProviderTarget", "agent_provider_scope", "answer_for_agent"]


@dataclass(frozen=True, slots=True)
class AgentProviderTarget:
    """The agent a provider read answers for; both ids blank means the serve's own home."""

    persona_instance_id: str | None = None
    persona_id: str | None = None

    @property
    def named(self) -> bool:
        return bool(self.persona_instance_id or self.persona_id)


def _persona_for(target: AgentProviderTarget) -> Any:
    from .config import ensure_persisted_personas, load_agent_runtime_config

    persona_id = target.persona_id
    if target.persona_instance_id:
        from .persona_assignments.store import PersonaInstanceStore

        try:
            instance = PersonaInstanceStore().get(target.persona_instance_id)
        except (FileNotFoundError, ValueError):
            raise ProviderRefused("agent_unknown", persona_instance_id=target.persona_instance_id) from None
        if persona_id and persona_id != instance.persona_id:
            raise ProviderRefused("agent_unknown", persona_instance_id=target.persona_instance_id,
                                  persona_id=persona_id)
        persona_id = instance.persona_id
    persona = next((row for row in ensure_persisted_personas(load_agent_runtime_config())
                    if row.id == persona_id), None)
    if persona is None:
        raise ProviderRefused("agent_unknown", persona_id=persona_id)
    return persona


@contextmanager
def agent_provider_scope(target: AgentProviderTarget) -> Iterator[dict | None]:
    """Bind the named agent's profile for the block; yield the echo (``None`` when unnamed)."""
    if not target.named:
        yield None
        return
    from . import paths
    from .profile_context import active_profile_name, persona_profile_context, resolve_persona_profile

    persona = _persona_for(target)
    binding = resolve_persona_profile(persona)
    if binding.readiness != "ready":
        raise ProviderRefused("agent_profile_unavailable", persona_id=persona.id, profile=binding.hermes_profile)
    with persona_profile_context(binding, runtime_root=paths.store_root()):
        yield {"persona_id": persona.id, "persona_instance_id": target.persona_instance_id,
               "profile": binding.hermes_profile or active_profile_name()}


def answer_for_agent(target: AgentProviderTarget, work: Callable[[], dict]) -> dict:
    """``work()`` under the agent's binding, its answer stamped with ``agent`` when one was named."""
    with agent_provider_scope(target) as echo:
        result = work()
    return result if echo is None else {**result, "agent": echo}
