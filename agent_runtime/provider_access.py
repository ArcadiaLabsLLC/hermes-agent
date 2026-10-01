"""Eternia's shared sign-in policy over Hermes-owned resources."""
from pathlib import Path

from agent.provider_access import ProviderAccess

from .provider_configuration import provider_configuration
from .provider_credentials import bound_provider_home, bound_provider_secret, provider_credential_file

__layer__ = "stores"


class SharedProviderAccess(ProviderAccess):
    name = "eternia-harness"

    def is_bound(self) -> bool:
        return bound_provider_home() is not None

    def secret(self, name: str) -> str:
        return bound_provider_secret(name) or ""

    def credential_file(self, name: str, profile_home: Path) -> Path:
        return provider_credential_file(name, profile_home)

    def configuration(self, profile: dict) -> dict:
        return provider_configuration(profile)
