"""Boolean distribution switches, shared by CLI and embedded runtimes."""

from __future__ import annotations


def config_switch(*keys: str, default: bool = True) -> bool:
    """A boolean feature switch at ``keys`` in the cached merged config (``load_config_readonly``).

    The one reader behind the switches a distribution turns off (``mcp.client``,
    ``mcp.stdio_servers``, ``terminal.external_backends``, ``gateway.platform_adapters``,
    ``voice.mode_enabled``, ``sessions.git_probe``): absent, ``null`` or an unreadable config is
    ``default`` (today's behaviour), a truthy word is on, anything else is off. Never raises."""
    from hermes_cli import config as _config

    try:
        value = _config.cfg_get(_config.load_config_readonly(), *keys, default=default)
    except Exception:
        return default
    from utils import is_truthy_value

    return is_truthy_value(value, default=default)
