"""Provider-only resource access, supplied by whatever plugin registers it.

A host that owns the provider relationship (an embedding app with its own auth, a
managed profile) registers ONE :class:`ProviderAccess` through
``PluginContext.register_provider_access``. While it reports ``is_bound()``, the
provider credential reads, the credential file the native readers/writers use,
and the provider definitions read from ``config.yaml`` come from it.

This port never loads plugins and never selects models or credentials itself;
native readers, refresh locks and writers stay authoritative. Nothing registered
(the default) means every reader returns exactly what it returned before.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from agent.provider_registry import ProviderRegistry


class ProviderAccess(ABC):
    """One explicitly bound provider authority; tool secrets are outside this port."""

    name: str

    @abstractmethod
    def is_bound(self) -> bool:
        """Whether this extension owns provider access in the calling context."""

    @abstractmethod
    def secret(self, name: str) -> str:
        """Return the value, or ``""`` for an authoritative miss. Never borrow another authority."""

    @abstractmethod
    def credential_file(self, name: str, profile_home: Path) -> Path:
        """Select the file native credential readers AND writers use."""

    @abstractmethod
    def configuration(self, profile: dict) -> dict:
        """Project provider definitions without mutating the profile or its file."""

    def forward_model_switch(self, server: Any, rid: Any, params: dict, session: dict) -> Optional[dict]:
        """Apply an idle compute-host session's model pick at its live owner.

        Return the JSON-RPC response, or ``None`` to keep the default (stash the pick for the
        next turn frame). Consulted only for compute-host sessions; the default never forwards.
        """
        return None


_registry = ProviderRegistry[ProviderAccess](
    label="Provider access", provider_cls=ProviderAccess,
    logger=logging.getLogger(__name__),
)
_registry.export(globals())


def current_access() -> Optional[ProviderAccess]:
    """The one bound access for the calling context, or None.

    Never runs plugin discovery: a host that owns provider access registers it when its
    plugin loads. More than one bound authority is a configuration error and raises.
    """
    bound = [access for access in _registry.list_providers() if access.is_bound()]
    if len(bound) > 1:
        raise RuntimeError("More than one provider authority is bound to this profile")
    return bound[0] if bound else None


def provider_secret(name: str) -> Optional[str]:
    """None means unbound; ``""`` is an authoritative miss. Errors propagate."""
    access = current_access()
    return None if access is None else access.secret(name)


def provider_credential_file(name: str, profile_home: Path) -> Path:
    access = current_access()
    return profile_home / name if access is None else access.credential_file(name, profile_home)


def provider_configuration(profile: dict) -> dict:
    access = current_access()
    return profile if access is None else access.configuration(profile)
