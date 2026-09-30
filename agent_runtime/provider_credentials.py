"""Provider-only reads from an explicitly bound credential owner.

Profile config, tools and memory keep their own home. No credential is copied.
"""
from __future__ import annotations

from pathlib import Path

from .profile_home import get_hermes_auth_home

__layer__ = "stores"


def bound_provider_home() -> Path | None:
    home = get_hermes_auth_home()
    return Path(home).expanduser().resolve() if home else None


def bound_provider_secret(key: str) -> str | None:
    """None means unbound; an empty bound value must not borrow a profile's key."""
    home = bound_provider_home()
    if home is None:
        return None
    from agent.secret_scope import build_profile_secret_scope
    from hermes_cli.env_loader import hydrate_profile_secret_sources

    hydrate_profile_secret_sources(home)
    return (build_profile_secret_scope(home).get(key) or "").strip()


def provider_credential_file(name: str, profile_home: Path) -> Path:
    return (bound_provider_home() or profile_home) / name
