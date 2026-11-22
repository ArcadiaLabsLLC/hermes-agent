"""``config_switch``: the one boolean reader behind the switches a distribution turns off, and
``with_install_switches``: the seam that holds a bundled install's shipped switches on every read."""

from __future__ import annotations

import copy
import logging
import threading
from typing import Any, Mapping

logger = logging.getLogger(__name__)

#: Keys a bundle profile sets that stay per profile BY DESIGN, each with the profile's own words. Every
#: other key a bundle profile's ``config`` sets is the install's (census on
#: RT-FU-A-BUNDLED-INSTALLS-SWITCHES-HOLD-ON-EVERY-PROFILE).
PER_PROFILE_KEYS: Mapping[str, str] = {
    "mcp.stdio_servers": ("bundled-desktop.yaml: an agent's profile may turn them on in its own config, as "
                          "upstream does (the operator adds the server; untrusted servers ask per call)"),
}

#: Keys a bundle profile sets that the edition only DEFAULTS: never held over the config, each with its
#: reason (owner ruling on RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG, 2026-11-21).
#: A person changes the first two in the normal config; holding them would make that change never take
#: effect. The third binds the OS store and moves sign-ins, and waits for its own row.
HELD_OUT_KEYS: Mapping[str, str] = {
    "local_runtime.enabled": "the dashboard's Local LLM Stop writes it (web_routers/local_models.py::_set_runtime_enabled)",
    "delegation.worktree_isolation": "Eternia's sub-agent settings write it (agent_runtime/subagents/settings.py::write_settings)",
    "auth.os_secure_store": "held means the secure-store sign-in move runs; it waits for its own row",
}

_UNSET: Any = object()
_install_switches: Any = _UNSET
_overlay_lock = threading.Lock()
#: ``id(config) -> (config, overlaid)``: ``load_config_readonly`` hands back the loader's cached dict, so
#: one overlay per cached dict is reused; the strong ref keeps an id from being reused while its entry lives.
_overlays: dict[int, tuple[dict, dict]] = {}
_OVERLAYS_MAX = 16


def config_switch(*keys: str, default: bool = True) -> bool:
    """A boolean feature switch at ``keys`` in the cached merged config (``load_config_readonly``).

    The one reader behind the switches a distribution turns off (``mcp.client``,
    ``mcp.stdio_servers``, ``terminal.external_backends``, ``gateway.platform_adapters``,
    ``voice.mode_enabled``, ``sessions.git_probe``): absent, ``null`` or an unreadable config is
    ``default`` (today's behaviour), a truthy word is on, anything else is off. Never raises.
    On a bundled install an install-only key reads the shipped profile's value under any profile
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
    desktop whose build stamp says ``bundled`` (``agent_runtime.installed_profile.install_is_bundled``)."""
    from agent_runtime import bundled_toolsets, installed_profile

    if not installed_profile.install_is_bundled():
        return None
    return bundled_toolsets.bundled_profile().config


def install_switches() -> tuple[tuple[tuple[str, ...], Any], ...]:
    """The installed bundle profile's install-only switches as ``(path, value)``; ``()`` on a developer install.

    Every key the shipped profile's ``config`` sets, minus :data:`PER_PROFILE_KEYS` and
    :data:`HELD_OUT_KEYS`, with the profile's own value. Read once per process (the install does not
    change under a running process); the values are private copies no caller can reach. Never raises:
    an unreadable profile is a developer install, today's behaviour."""
    global _install_switches
    switches = _install_switches
    if switches is not _UNSET:
        return switches
    _install_switches = ()  # a config read while the profile loads holds nothing (no re-entry)
    try:
        config = _installed_profile_config()
        switches = () if not config else tuple(
            (tuple(dotted.split(".")), copy.deepcopy(value)) for dotted, value in config.items()
            if dotted not in PER_PROFILE_KEYS and dotted not in HELD_OUT_KEYS)
    except Exception:  # health: allow BLE001 -- the read seam never raises; no profile is today's behaviour
        logger.warning("install switches: the bundle profile is unreadable; no key is held", exc_info=True)
        switches = ()
    _install_switches = switches
    return switches


def install_only_keys() -> tuple[tuple[str, ...], ...]:
    """The paths :func:`install_switches` holds, split on dots; ``()`` on a developer install."""
    return tuple(path for path, _value in install_switches())


def reset_install_switches() -> None:
    """Forget the install's switches and the cached overlays (tests that install a profile)."""
    global _install_switches
    with _overlay_lock:
        _install_switches = _UNSET
        _overlays.clear()


def _lookup(config: Mapping[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    node: Any = config
    for part in path:
        if not isinstance(node, Mapping) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _put(node: Any, path: tuple[str, ...], value: Any) -> dict:
    """A copy of ``node`` with ``path`` set to ``value``: only the mappings along the path are copied."""
    copy_ = dict(node) if isinstance(node, Mapping) else {}
    head, *rest = path
    copy_[head] = copy.deepcopy(value) if not rest else _put(copy_.get(head), tuple(rest), value)
    return copy_


def _overlay(config: dict, switches: tuple) -> dict:
    result = config
    for path, value in switches:
        if _lookup(result, path) != (True, value):
            result = _put(result, path, value)
    return result


def with_install_switches(config: dict, *, cache: bool = True) -> dict:
    """``config`` with each install-only switch of the shipped bundle profile held at the profile's value.

    THE seam that holds a bundled install's switches on every read, every profile and the serve root
    alike: the shipped profile (``bundled-desktop.yaml`` / ``bundled-phone.yaml``) is read once
    (:func:`install_switches`) and laid over the config in memory. Nothing is written: the bundled
    desktop's serve root is the account's shared namespace home, which the Developer Edition opens too,
    so a written switch would lock the Developer Edition down as well (owner ruling on
    RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG). :data:`PER_PROFILE_KEYS` and
    :data:`HELD_OUT_KEYS` follow the config. A developer install keeps ``config`` as is. ``config`` is
    never mutated; ``cache`` reuses one overlay per cached dict (``load_config_readonly``'s), and a
    caller holding a fresh copy passes ``cache=False``. Never raises."""
    switches = install_switches()
    if not switches or not isinstance(config, Mapping):
        return config
    if not cache:
        return _overlay(config, switches)
    slot = id(config)
    with _overlay_lock:
        hit = _overlays.get(slot)
    if hit is not None and hit[0] is config:
        return hit[1]
    result = _overlay(config, switches)
    with _overlay_lock:
        if len(_overlays) >= _OVERLAYS_MAX:
            _overlays.clear()
        _overlays[slot] = (config, result)
    return result
