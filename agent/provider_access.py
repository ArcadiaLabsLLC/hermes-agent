"""Provider-only resource access, supplied by whatever is registered.

Plugins register when they load; this port never loads them. A bound provider
home registers the harness's access on first read. This boundary selects
resources, not models or credentials. Native readers, refresh locks and writers
remain authoritative. No extension means no override.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from agent.provider_registry import ProviderRegistry


class ProviderAccess(ABC):
    """One explicitly bound provider authority; tool secrets are outside this port."""

    name: str

    @abstractmethod
    def is_bound(self) -> bool:
        """Whether this extension owns provider access in the calling context."""

    @abstractmethod
    def secret(self, name: str) -> str:
        """Return the value, or empty when absent. Never borrow another authority."""

    @abstractmethod
    def credential_file(self, name: str, profile_home: Path) -> Path:
        """Select the file native credential readers AND writers use."""

    @abstractmethod
    def configuration(self, profile: dict) -> dict:
        """Project provider definitions without mutating the profile or its file."""


_registry = ProviderRegistry[ProviderAccess](
    label="Provider access", provider_cls=ProviderAccess,
    logger=logging.getLogger(__name__),
)
_registry.export(globals())


def _bound_access() -> list[ProviderAccess]:
    return [access for access in _registry.list_providers() if access.is_bound()]


def current_access() -> ProviderAccess | None:
    # Never runs plugin discovery: that cost (650-900 ms at v0.21.6's 53 plugins) and its
    # side effects (loader threads, plugin-time writes) sat on the first credential read
    # of every process. A process whose provider home is bound registers the harness's
    # access itself; an unbound process has no authority to find.
    bound = _bound_access()
    if not bound:
        from agent_runtime.profile_home import get_hermes_auth_home

        if get_hermes_auth_home():
            from agent_runtime.provider_access import ensure_shared_provider_access_registered

            if ensure_shared_provider_access_registered():
                bound = _bound_access()
    if len(bound) > 1:
        raise RuntimeError("More than one provider authority is bound to this profile")
    return bound[0] if bound else None


def provider_secret(name: str) -> str | None:
    """None means unbound; empty is an authoritative miss. Errors propagate."""
    access = current_access()
    return None if access is None else access.secret(name)


def provider_credential_file(name: str, profile_home: Path) -> Path:
    access = current_access()
    return profile_home / name if access is None else access.credential_file(name, profile_home)


def provider_configuration(profile: dict) -> dict:
    access = current_access()
    return profile if access is None else access.configuration(profile)
