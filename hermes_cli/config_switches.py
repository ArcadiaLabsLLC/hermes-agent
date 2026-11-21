"""``config_switch``: the one boolean reader behind the switches a distribution turns off, and
``with_install_switches``: the seam that holds a bundled install's switches on every profile."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any, Mapping

logger = logging.getLogger(__name__)

#: Keys a bundle profile sets that stay per profile BY DESIGN, each with the profile's own words. Every
#: other key a bundle profile's ``config`` sets is the install's (census on
#: RT-FU-A-BUNDLED-INSTALLS-SWITCHES-HOLD-ON-EVERY-PROFILE).
PER_PROFILE_KEYS: Mapping[str, str] = {
    "mcp.stdio_servers": "bundled-desktop.yaml: an agent's profile may turn them on, with approvals",
}

_UNSET: Any = object()
_install_keys: Any = _UNSET
_overlay_lock = threading.Lock()
#: ``(id(scoped), id(root)) -> (scoped, root, overlaid)``: the loader hands back its cached dicts, so one
#: overlay per pair is reused; the strong refs keep an id from being reused while its entry lives.
_overlays: dict[tuple[int, int], tuple[dict, dict, dict]] = {}
_OVERLAYS_MAX = 16


def config_switch(*keys: str, default: bool = True) -> bool:
    """A boolean feature switch at ``keys`` in the cached merged config (``load_config_readonly``).

    The one reader behind the switches a distribution turns off (``mcp.client``,
    ``mcp.stdio_servers``, ``terminal.external_backends``, ``gateway.platform_adapters``,
    ``voice.mode_enabled``, ``sessions.git_probe``): absent, ``null`` or an unreadable config is
    ``default`` (today's behaviour), a truthy word is on, anything else is off. Never raises.
    On a bundled install an install-only key reads the serve root's value under any profile
    (:func:`with_install_switches`, applied by ``load_config_readonly``)."""
    from hermes_cli import config as _config
    from utils import is_truthy_value

    try:
        value = _config.cfg_get(_config.load_config_readonly(), *keys, default=default)
    except Exception:  # health: allow BLE001 -- a switch never raises; an unreadable config is the default
        logger.debug("config_switch %s: config unreadable; using default=%s", ".".join(keys), default,
                     exc_info=True)
        return default
    return is_truthy_value(value, default=default)


def _installed_profile_config() -> Mapping[str, Any] | None:
    """The installed bundle profile's ``config`` block, or ``None`` on a developer install.

    A bundled install is a phone (CPython's mobile platforms run only the embedded phone profile) or a
    desktop whose build stamp says ``bundled`` (``agent_runtime.bundled_toolsets.edition_bundled``)."""
    from agent_runtime import bundled_toolsets

    if sys.platform not in bundled_toolsets.PHONE_PLATFORMS and not bundled_toolsets.edition_bundled():
        return None
    return bundled_toolsets.bundled_profile().config


def install_only_keys() -> tuple[tuple[str, ...], ...]:
    """The install-only keys of the installed bundle profile, split on dots; ``()`` on a developer install.

    Read once per process (the install does not change under a running process). Never raises: an
    unreadable profile is a developer install, today's behaviour."""
    global _install_keys
    keys = _install_keys
    if keys is not _UNSET:
        return keys
    _install_keys = ()  # a config read while the profile loads holds nothing (no re-entry)
    try:
        config = _installed_profile_config()
        keys = () if not config else tuple(
            tuple(dotted.split(".")) for dotted in config if dotted not in PER_PROFILE_KEYS)
    except Exception:  # health: allow BLE001 -- the read seam never raises; no profile is today's behaviour
        logger.warning("install switches: the bundle profile is unreadable; no key is held", exc_info=True)
        keys = ()
    _install_keys = keys
    return keys


def reset_install_switches() -> None:
    """Forget the install's keys and the cached overlays (tests that install a profile)."""
    global _install_keys
    with _overlay_lock:
        _install_keys = _UNSET
        _overlays.clear()


def _root_config() -> dict | None:
    """The serve root's merged config, or ``None`` when the call is not scoped away from the root."""
    from hermes_cli import config as _config
    from hermes_constants import (
        get_hermes_home,
        get_routing_process_hermes_home,
        hermes_home_key,
        reset_hermes_home_override,
        set_hermes_home_override,
    )

    root = get_routing_process_hermes_home()
    if hermes_home_key(get_hermes_home()) == hermes_home_key(root):
        return None
    token = set_hermes_home_override(root)
    try:
        # The loader itself, not ``load_config_readonly``: the root's own config, never re-projected.
        return _config._load_config_impl(want_deepcopy=False, ensure_home=False)
    finally:
        reset_hermes_home_override(token)


def _lookup(config: Mapping[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    node: Any = config
    for part in path:
        if not isinstance(node, Mapping) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _put(node: Any, path: tuple[str, ...], value: Any) -> dict:
    """A copy of ``node`` with ``path`` set to ``value``: only the mappings along the path are copied."""
    copy = dict(node) if isinstance(node, Mapping) else {}
    head, *rest = path
    copy[head] = value if not rest else _put(copy.get(head), tuple(rest), value)
    return copy


def with_install_switches(config: dict) -> dict:
    """``config`` with each install-only key the serve root's config sets taken from the root.

    THE seam that holds a bundled install's switches on every profile: a bundle profile's switches are
    written to the serve root's config, and a call scoped to a second profile reads that profile's
    home, so without this a second profile reads the default (on) of every switch the install turned
    off (``tui_gateway.pydantic_contracts``, ``auth.adopt_external_logins``, ...). Only the keys the
    installed profile forces, minus :data:`PER_PROFILE_KEYS`, and only where the root sets them; a
    developer install, a call scoped to the root, and an unreadable root config keep ``config`` as is.
    ``config`` is the loader's cached dict and is never mutated. Never raises."""
    keys = install_only_keys()
    if not keys:
        return config
    try:
        root_config = _root_config()
    except Exception:  # health: allow BLE001 -- the read seam never raises; an unreadable root holds nothing
        logger.debug("install switches: the serve root's config is unreadable", exc_info=True)
        return config
    if not isinstance(root_config, Mapping):
        return config
    slot = (id(config), id(root_config))
    with _overlay_lock:
        hit = _overlays.get(slot)
    if hit is not None and hit[0] is config and hit[1] is root_config:
        return hit[2]
    result = config
    for path in keys:
        found, value = _lookup(root_config, path)
        if found and _lookup(result, path) != (True, value):
            result = _put(result, path, value)
    with _overlay_lock:
        if len(_overlays) >= _OVERLAYS_MAX:
            _overlays.clear()
        _overlays[slot] = (config, root_config, result)
    return result
