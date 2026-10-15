"""Read shared provider definitions without changing profile configuration."""
from pathlib import Path

from .provider_credentials import bound_provider_home

__layer__ = "stores"
_CONNECTION_KEYS = ("providers", "custom_providers", "model_catalog")


def configuration_at(home: Path) -> dict:
    from agent.secret_scope import build_profile_secret_scope, reset_secret_scope, set_secret_scope
    from hermes_cli.config_effective import load_user_config_effective
    from hermes_cli.env_loader import hydrate_profile_secret_sources
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    home_token = set_hermes_home_override(home)
    secret_token = None
    try:
        hydrate_profile_secret_sources(home)
        secret_token = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
        return load_user_config_effective(home / "config.yaml", fail_closed=True)
    finally:
        if secret_token is not None:
            reset_secret_scope(secret_token)
        reset_hermes_home_override(home_token)


def provider_configuration(profile: dict) -> dict:
    from hermes_constants import get_hermes_home

    owner = bound_provider_home()
    if owner is None or owner == get_hermes_home().resolve():
        return profile
    shared = configuration_at(owner)
    result = {key: value for key, value in profile.items() if key not in _CONNECTION_KEYS}
    result.update({key: shared[key] for key in _CONNECTION_KEYS if key in shared})
    return result
