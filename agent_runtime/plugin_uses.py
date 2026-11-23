"""Which plugins a readied agent uses, so the snapshot worker loads only those.

Owner ruling 2026-11-22: "it should load only the plugins it uses", and on the
upstream footprint: "its fine as long as its a thin entry into upstream code".
The thin entry is ``hermes_cli.plugins.set_plugin_load_filter``; every decision
about WHICH plugins lives here.

What a plugin uses is read off what it REGISTERS, never off its manifest's
names: ``eternia-harness`` registers ``skill_search`` into the builtin ``skills``
toolset, which no manifest field says. :func:`record_plugin_uses` loads every
plugin with its registrations recorded — each ``PluginContext.register_*`` call
(a tool with its toolset) and every other piece of manager state the load grew —
and ``scripts/dump_plugin_uses.py`` commits the answer as
``agent_runtime/plugin_uses.json``. ``tests/agent_runtime/test_plugin_uses.py``
re-records it live and refuses a committed file that is missing anything a
plugin registers here.

A plugin is held back only when the record PROVES the build does not need it:
everything it registers is a tool in a toolset no readied agent uses, a provider
for such a toolset (an image or video backend, a web search or browser backend,
TTS, delegation), or a messaging platform (the worker runs no gateway). Anything
else — a hook, middleware, provider access, a secret source, skills, any state
not named here, a plugin that registered nothing where it was recorded, or one
the record does not know — is admitted.

The filter is installed only in the snapshot worker (:func:`enable_selective_load`
from ``snapshot_worker.child``), which builds the read model and runs no turns.
The serve keeps loading every enabled plugin. When a newly readied agent needs a
plugin the worker held back, :func:`admit_for_toolsets` widens the filter and
re-runs discovery once.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from .process_state import register_process_state

__layer__ = "stores"

logger = logging.getLogger(__name__)

PLUGIN_USES_PATH = Path(__file__).resolve().parent / "plugin_uses.json"
PLUGIN_USES_SCHEMA_VERSION = 1

#: A provider registration and the toolsets whose tools reach it.
PROVIDER_TOOLSETS: dict[str, frozenset[str]] = {
    "register_image_gen_provider": frozenset({"image_gen"}),
    "register_video_gen_provider": frozenset({"video_gen", "video"}),
    "register_web_search_provider": frozenset({"web"}),
    "register_browser_provider": frozenset({"browser", "browser-cdp", "browser-use"}),
    "register_browser_page_backend": frozenset({"browser", "browser-cdp", "browser-use"}),
    "register_tts_provider": frozenset({"tts"}),
    "register_delegation_provider": frozenset({"delegation"}),
}
#: Registrations no snapshot build reads: messaging platforms (the worker runs no gateway).
NOT_READ_BY_A_BUILD = frozenset({"register_platform"})
#: Manager state a load grows as bookkeeping for a registration recorded by name above.
BOOKKEEPING_STATE = frozenset(
    {"_ownership_ledger", "_registration_order", "_plugin_tool_names", "_plugin_platform_names"}
)

RECEIPT = "plugin_uses op=%s admitted=%d held=%d toolsets=%d pid=%d"

_lock = threading.Lock()
_state: dict[str, Any] = {"enabled": False, "toolsets": None}


def _reset() -> None:
    import sys

    with _lock:
        _state["enabled"] = False
        _state["toolsets"] = None
    plugins = sys.modules.get("hermes_cli.plugins")
    if plugins is not None:
        plugins.set_plugin_load_filter(None)


register_process_state(__name__, _reset, holds=("_state",))


# ── recording ────────────────────────────────────────────────────────────────


def _manager_state_sizes(manager: Any) -> dict[str, int]:
    return {
        name: len(value)
        for name, value in vars(manager).items()
        if isinstance(value, (dict, list, set)) and name != "_plugins"
    }


def record_plugin_uses() -> dict[str, dict[str, list[str]]]:
    """Discover every enabled plugin of the current home with its registrations recorded.

    ``{plugin key: {"toolsets": [...], "registers": [...]}}``: the toolsets its
    tools went into, and every other ``register_*`` call or ``state:<attr>`` the
    load grew. Only the plugins that loaded here are recorded.
    """

    from hermes_cli import plugins as plugin_mod
    from hermes_cli.plugins_context import PluginContext
    from hermes_cli.plugins_discovery import manifest_key

    recorded: dict[str, dict[str, set[str]]] = {}

    def entry(key: str) -> dict[str, set[str]]:
        return recorded.setdefault(key, {"toolsets": set(), "registers": set()})

    originals: dict[str, Any] = {}
    for name in dir(PluginContext):
        method = getattr(PluginContext, name)
        if not name.startswith("register_") or not callable(method):
            continue
        originals[name] = method

        def traced(self, *args, _name=name, _method=method, **kwargs):
            row = entry(self.plugin_id)
            if _name == "register_tool":
                toolset = kwargs.get("toolset", args[1] if len(args) > 1 else None)
                row["toolsets"].add(str(toolset))
            else:
                row["registers"].add(_name)
            return _method(self, *args, **kwargs)

        setattr(PluginContext, name, traced)
    load = plugin_mod.PluginManager._load_plugin

    def traced_load(self, manifest):
        before = _manager_state_sizes(self)
        load(self, manifest)
        after = _manager_state_sizes(self)
        grew = {name for name in after if after[name] != before.get(name)} - BOOKKEEPING_STATE
        if grew or manifest_key(manifest) in recorded:
            entry(manifest_key(manifest))["registers"].update(f"state:{name}" for name in grew)

    plugin_mod.PluginManager._load_plugin = traced_load
    try:
        manager = plugin_mod.get_plugin_manager()
        manager.discover_and_load(force=True)
        loaded = {key for key, plugin in manager._plugins.items() if plugin.enabled and not plugin.error and not plugin.deferred}
    finally:
        plugin_mod.PluginManager._load_plugin = load
        for name, method in originals.items():
            setattr(PluginContext, name, method)
    return {
        key: {"toolsets": sorted(recorded.get(key, {}).get("toolsets", ())),
              "registers": sorted(recorded.get(key, {}).get("registers", ()))}
        for key in sorted(loaded)
    }


# ── the committed record ─────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def committed_plugin_uses() -> dict[str, dict[str, tuple[str, ...]]]:
    """The committed record; an unreadable file is an empty record (every plugin admitted)."""

    try:
        data = json.loads(PLUGIN_USES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return {}
    return {
        str(key): {"toolsets": tuple(row.get("toolsets") or ()), "registers": tuple(row.get("registers") or ())}
        for key, row in plugins.items()
        if isinstance(row, dict)
    }


def needed(key: str, toolsets: frozenset[str], record: dict | None = None) -> bool:
    """Whether a build readying agents with ``toolsets`` needs the plugin ``key``."""

    row = (committed_plugin_uses() if record is None else record).get(key)
    if row is None:
        return True  # unknown to the record: admitted
    registers = set(row["registers"])
    if not registers and not row["toolsets"]:
        return True  # registered nothing where it was recorded: may register here
    if set(row["toolsets"]) & toolsets:
        return True
    for name in registers:
        if name in NOT_READ_BY_A_BUILD:
            continue
        reaches = PROVIDER_TOOLSETS.get(name)
        # MUTATION: treat an unnamed registration as droppable and
        # test_plugin_uses' "a plugin that registers anything else is admitted" reddens.
        if reaches is None or reaches & toolsets:
            return True
    return False


# ── the worker's filter ──────────────────────────────────────────────────────


def enable_selective_load() -> None:
    """Hold back plugins no readied agent uses, in THIS process (the snapshot worker only)."""

    with _lock:
        _state["enabled"] = True


def admit_for_toolsets(toolsets: Iterable[str]) -> None:
    """Admit the plugins agents with ``toolsets`` use; re-discover when that widens a held set.

    A no-op outside a process that called :func:`enable_selective_load`.
    """

    import os

    from hermes_cli import plugins as plugin_mod
    from hermes_cli.plugins_discovery import manifest_key

    wanted = frozenset(str(name) for name in toolsets)
    record = committed_plugin_uses()
    with _lock:
        if not _state["enabled"]:
            return
        previous = _state["toolsets"]
        if previous is not None and wanted <= previous:
            return
        admitted = wanted if previous is None else previous | wanted
        _state["toolsets"] = admitted
    plugin_mod.set_plugin_load_filter(lambda manifest: needed(manifest_key(manifest), admitted))
    held = {key for key in record if not needed(key, admitted, record)}
    logger.info(RECEIPT, "install" if previous is None else "widen", len(record) - len(held), len(held),
                len(admitted), os.getpid())
    if previous is None:
        return
    # Discovery already ran under the narrower filter: re-run it only when a plugin
    # it held back is needed now.
    was_held = {key for key in record if not needed(key, previous, record)}
    manager = plugin_mod.get_plugin_manager()
    if was_held - held and getattr(manager, "_discovered", False):
        manager.discover_and_load(force=True)
