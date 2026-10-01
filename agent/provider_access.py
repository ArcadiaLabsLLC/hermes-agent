"""Provider-only resource access, supplied by the active profile's plugins.

This boundary selects resources, not models or credentials. Native readers,
refresh locks and writers remain authoritative. No extension means no override.
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


def current_access() -> ProviderAccess | None:
    from hermes_cli.plugins import discover_plugins

    discover_plugins()
    bound = [access for access in _registry.list_providers() if access.is_bound()]
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
