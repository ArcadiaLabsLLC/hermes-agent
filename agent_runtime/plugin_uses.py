"""Which plugins a readied agent uses, so a process loads only those, each once.

Owner rulings 2026-11-22/23: "it should load only the plugins it uses", "load
each plugin once, and only the ones the readied agent uses", and on the upstream
footprint: "its fine as long as its a thin entry into upstream code". The thin
entries are ``hermes_cli.plugins.set_plugin_load_filter`` and
``PluginManager.load_admitted``; every decision about WHICH plugins lives here.

What a plugin uses is read off what it REGISTERS, never off its manifest's
names: ``eternia-harness`` registers ``skill_search`` into the builtin ``skills``
toolset, which no manifest field says. Two records say it, both taken the same
way (:func:`_trace_registrations`: each ``PluginContext.register_*`` call, a
tool with its toolset, and every other piece of manager state a load grew):

* the COMMITTED record, ``agent_runtime/plugin_uses.json``, for the plugins in
  Hermes's own tree (``scripts/dump_plugin_uses.py``;
  ``tests/agent_runtime/test_plugin_uses.py`` re-records it live);
* each home's LOCAL record, ``<home>/state/plugin_uses.json``, for every other
  plugin (a catalog or user plugin such as ``homeassistant``), keyed by name and
  version and written by the selecting process that first loads it. A plugin
  neither record knows is loaded and recorded; from then on it is held like the
  others.

A plugin is held back only when its record PROVES nothing readied needs it:
everything it registers is a tool in a toolset no readied agent uses, a provider
for such a toolset (an image or video backend, a web search or browser backend,
TTS, delegation), or a messaging platform in a process that runs none (the
snapshot worker). Anything else — a hook, middleware, provider access, a secret
source, skills, any state not named here, or a plugin that registered nothing
where it was recorded — is admitted.

Two processes select: the snapshot worker (:func:`enable_selective_load`, from
``snapshot_worker.child``) and the serve (``serve=True``, from its production
wiring; it keeps every platform plugin, since it runs the messaging lanes). The
toolsets widen on demand — a build's readied agents, a persona prewarm, and every
tool-definition list (``tools.tool_defs_observability``) — and a widening loads
only the plugins it newly admits (``load_admitted``), never re-loading the rest.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import weakref
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from .process_state import register_process_state

__layer__ = "stores"

logger = logging.getLogger(__name__)

PLUGIN_USES_PATH = Path(__file__).resolve().parent / "plugin_uses.json"
PLUGIN_USES_SCHEMA_VERSION = 1
#: A home's record of the plugins the committed record does not know, under that home.
LOCAL_RECORD_PARTS = ("state", "plugin_uses.json")

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
#: Toolset names that resolve to every toolset (``toolsets.resolve_toolset``).
EVERY_TOOLSET = frozenset({"all", "*"})
#: Messaging platforms: read only by a process that runs a messaging lane (the serve).
PLATFORM_REGISTRATIONS = frozenset({"register_platform"})
#: Manager state a load grows as bookkeeping for a registration recorded by name above.
BOOKKEEPING_STATE = frozenset(
    {"_ownership_ledger", "_registration_order", "_plugin_tool_names", "_plugin_platform_names"}
)

RECEIPT = "plugin_uses op=%s admitted=%d held=%d toolsets=%d pid=%d"
RECORDED_RECEIPT = "plugin_uses op=recorded plugin=%s version=%s toolsets=%d registers=%d pid=%d"

_lock = threading.RLock()
_state: dict[str, Any] = {
    "enabled": False,
    "toolsets": None,  # frozenset once installed
    "all": False,  # a caller asked for every toolset
    "platforms": False,  # this process runs messaging lanes
    "generation": 0,  # bumped on every widening
    "untrace": None,  # restores the live recording's patches
}
#: manager -> the generation it last loaded under.
_synced: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
#: home -> its local record, read once per process.
_local: dict[str, dict[str, dict[str, Any]]] = {}
#: home -> {plugin key: its row} for the plugins this home's discoveries held back.
_held: dict[str, dict[str, Any]] = {}
#: plugin key -> registrations of a load in progress (plugins the committed record does not know).
_loading: dict[str, dict[str, set[str]]] = {}


def _reset() -> None:
    import sys

    with _lock:
        untrace = _state["untrace"]
        _state.update(enabled=False, toolsets=None, all=False, platforms=False, generation=0, untrace=None)
        _synced.clear()
        _local.clear()
        _held.clear()
        _loading.clear()
    if untrace is not None:
        untrace()
    plugins = sys.modules.get("hermes_cli.plugins")
    if plugins is not None:
        plugins.set_plugin_load_filter(None)


register_process_state(__name__, _reset, holds=("_state", "_synced", "_local", "_held", "_loading"))


# ── recording ────────────────────────────────────────────────────────────────


def _manager_state_sizes(manager: Any) -> dict[str, int]:
    return {
        name: len(value)
        for name, value in vars(manager).items()
        if isinstance(value, (dict, list, set)) and name != "_plugins"
    }


def _trace_registrations(
    on_register: Callable[[str, str, tuple, dict], None],
    on_load: Callable[[Any, Any, set[str]], None],
) -> Callable[[], None]:
    """Report every ``register_*`` call and every plugin load; returns the undo.

    ``on_register(plugin key, method name, args, kwargs)`` runs before the call;
    ``on_load(manager, manifest, grown state names)`` after each load.
    """

    from hermes_cli import plugins as plugin_mod
    from hermes_cli.plugins_context import PluginContext

    originals: dict[str, Any] = {}
    for name in dir(PluginContext):
        method = getattr(PluginContext, name)
        if not name.startswith("register_") or not callable(method):
            continue
        originals[name] = method

        def traced(self, *args, _name=name, _method=method, **kwargs):
            on_register(self.plugin_id, _name, args, kwargs)
            return _method(self, *args, **kwargs)

        setattr(PluginContext, name, traced)
    load = plugin_mod.PluginManager._load_plugin

    def traced_load(self, manifest):
        before = _manager_state_sizes(self)
        load(self, manifest)
        after = _manager_state_sizes(self)
        on_load(self, manifest, {name for name in after if after[name] != before.get(name)} - BOOKKEEPING_STATE)

    plugin_mod.PluginManager._load_plugin = traced_load

    def untrace() -> None:
        plugin_mod.PluginManager._load_plugin = load
        for name, method in originals.items():
            setattr(PluginContext, name, method)

    return untrace


def _note_registration(row: dict[str, set[str]], name: str, args: tuple, kwargs: dict) -> None:
    if name == "register_tool":
        row["toolsets"].add(str(kwargs.get("toolset", args[1] if len(args) > 1 else None)))
    else:
        row["registers"].add(name)


def _blank() -> dict[str, set[str]]:
    return {"toolsets": set(), "registers": set()}


def record_plugin_uses() -> dict[str, dict[str, list[str]]]:
    """Discover every enabled plugin of the current home with its registrations recorded.

    ``{plugin key: {"toolsets": [...], "registers": [...]}}``: the toolsets its
    tools went into, and every other ``register_*`` call or ``state:<attr>`` the
    load grew. Only the plugins that loaded here are recorded.
    """

    from hermes_cli import plugins as plugin_mod
    from hermes_cli.plugins_discovery import manifest_key

    recorded: dict[str, dict[str, set[str]]] = {}

    def on_register(key: str, name: str, args: tuple, kwargs: dict) -> None:
        _note_registration(recorded.setdefault(key, _blank()), name, args, kwargs)

    def on_load(_manager: Any, manifest: Any, grew: set[str]) -> None:
        if grew or manifest_key(manifest) in recorded:
            recorded.setdefault(manifest_key(manifest), _blank())["registers"].update(f"state:{n}" for n in grew)

    untrace = _trace_registrations(on_register, on_load)
    try:
        manager = plugin_mod.get_plugin_manager()
        manager.discover_and_load(force=True)
        loaded = {key for key, plugin in manager._plugins.items() if plugin.enabled and not plugin.error and not plugin.deferred}
    finally:
        untrace()
    return {
        key: {"toolsets": sorted(recorded.get(key, {}).get("toolsets", ())),
              "registers": sorted(recorded.get(key, {}).get("registers", ()))}
        for key in sorted(loaded)
    }


# ── the records ──────────────────────────────────────────────────────────────


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


def local_record_path(home: Path | str) -> Path:
    return Path(home).joinpath(*LOCAL_RECORD_PARTS)


def _home_key(home: Path | str) -> str:
    return str(Path(home).resolve())


def local_plugin_uses(home: Path | str) -> dict[str, dict[str, Any]]:
    """``home``'s local record: ``{key: {"version", "toolsets", "registers"}}``; unreadable = empty."""

    key = _home_key(home)
    with _lock:
        if key in _local:
            return _local[key]
    try:
        data = json.loads(local_record_path(home).read_text(encoding="utf-8"))
        plugins = data.get("plugins") if isinstance(data, dict) else None
    except (OSError, ValueError):
        plugins = None
    rows = {
        str(name): {"version": str(row.get("version") or ""), "toolsets": tuple(row.get("toolsets") or ()),
                    "registers": tuple(row.get("registers") or ())}
        for name, row in (plugins if isinstance(plugins, dict) else {}).items()
        if isinstance(row, dict)
    }
    with _lock:
        return _local.setdefault(key, rows)


def _write_local_row(home: Path | str, plugin: str, version: str, row: dict[str, set[str]]) -> None:
    from .serde import write_json_atomic

    entry = {"version": version, "toolsets": tuple(sorted(row["toolsets"])),
             "registers": tuple(sorted(row["registers"]))}
    path = local_record_path(home)
    with _lock:
        local_plugin_uses(home)[plugin] = entry
        try:  # merge onto the file: the other selecting process may have recorded meanwhile
            on_disk = json.loads(path.read_text(encoding="utf-8")).get("plugins") or {}
        except (OSError, ValueError, AttributeError):
            on_disk = {}
        merged = {**on_disk, plugin: {k: list(v) if isinstance(v, tuple) else v for k, v in entry.items()}}
        try:
            write_json_atomic(path, {"schema_version": PLUGIN_USES_SCHEMA_VERSION, "plugins": dict(sorted(merged.items()))})
        except OSError:
            logger.debug("plugin_uses local record not written for %s", plugin, exc_info=True)
            return
    logger.info(RECORDED_RECEIPT, plugin, version or "-", len(entry["toolsets"]), len(entry["registers"]), os.getpid())


def record_row(key: str, version: Any, home: Path | str | None = None) -> dict | None:
    """What ``key`` registers: the committed row, else this home's row for this version, else ``None``."""

    row = committed_plugin_uses().get(key)
    if row is not None:
        return row
    if home is None:
        from hermes_constants import get_hermes_home

        home = get_hermes_home()
    local = local_plugin_uses(home).get(key)
    if local is None or local["version"] != str(version or ""):
        return None
    return local


def _row_needed(row: dict | None, toolsets: frozenset[str], platforms: bool) -> bool:
    if row is None:
        return True  # unknown to both records: loaded, and recorded as it loads
    registers = set(row["registers"])
    if not registers and not row["toolsets"]:
        return True  # registered nothing where it was recorded: may register here
    if set(row["toolsets"]) & toolsets:
        return True
    for name in registers:
        if name in PLATFORM_REGISTRATIONS:
            # MUTATION: hold platforms in the serve too and test_plugin_uses'
            # "the serve keeps every platform plugin" reddens.
            if platforms:
                return True
            continue
        reaches = PROVIDER_TOOLSETS.get(name)
        # MUTATION: treat an unnamed registration as droppable and
        # test_plugin_uses' "a plugin that registers anything else is admitted" reddens.
        if reaches is None or reaches & toolsets:
            return True
    return False


def needed(key: str, toolsets: frozenset[str], record: dict | None = None, *, platforms: bool = False) -> bool:
    """Whether a process readying agents with ``toolsets`` needs the plugin ``key``."""

    return _row_needed((committed_plugin_uses() if record is None else record).get(key), toolsets, platforms)


# ── the live recording ───────────────────────────────────────────────────────


def _live_register(key: str, name: str, args: tuple, kwargs: dict) -> None:
    if key in committed_plugin_uses():
        return
    with _lock:
        _note_registration(_loading.setdefault(key, _blank()), name, args, kwargs)


def _live_load(manager: Any, manifest: Any, grew: set[str]) -> None:
    from hermes_cli.plugins_discovery import manifest_key

    key = manifest_key(manifest)
    if key in committed_plugin_uses():
        return
    with _lock:
        row = _loading.pop(key, None) or _blank()
    row["registers"].update(f"state:{name}" for name in grew)
    home = getattr(manager, "home_path", None)
    version = str(getattr(manifest, "version", "") or "")
    if home is not None and record_row(key, version, home) is None:
        # MUTATION: drop this write and test_plugin_uses' "a plugin outside
        # the committed record is recorded on first load, then held" reddens.
        _write_local_row(home, key, version, row)


def _start_live_recording() -> None:
    with _lock:
        if _state["untrace"] is not None:
            return
        _state["untrace"] = _trace_registrations(_live_register, _live_load)


# ── the filter ───────────────────────────────────────────────────────────────


def member_toolsets(names: Iterable[str]) -> frozenset[str]:
    """``names`` with every toolset they include, recursively (a composite and its members)."""

    from toolsets import TOOLSETS

    out: set[str] = set()
    stack = [str(name) for name in names if name]
    while stack:
        name = stack.pop()
        if name in out:
            continue
        out.add(name)
        stack.extend(str(member) for member in (TOOLSETS.get(name) or {}).get("includes", ()) or ())
    return frozenset(out)


def _admits(manifest: Any) -> bool:
    from hermes_cli.plugins_discovery import manifest_key
    from hermes_constants import get_hermes_home

    with _lock:
        if _state["all"]:
            return True
        toolsets, platforms = _state["toolsets"] or frozenset(), _state["platforms"]
    home = get_hermes_home()  # the manager's own home: discovery runs inside its home scope
    row = record_row(manifest_key(manifest), getattr(manifest, "version", ""), home)
    if _row_needed(row, toolsets, platforms):
        return True
    with _lock:
        _held.setdefault(_home_key(home), {})[manifest_key(manifest)] = row
    return False


def _log_receipt(op: str) -> None:
    from hermes_constants import get_hermes_home

    with _lock:
        toolsets, platforms, every = _state["toolsets"] or frozenset(), _state["platforms"], _state["all"]
    rows = {**local_plugin_uses(get_hermes_home()), **committed_plugin_uses()}
    held = 0 if every else sum(1 for row in rows.values() if not _row_needed(row, toolsets, platforms))
    logger.info(RECEIPT, op, len(rows) - held, held, len(toolsets), os.getpid())


def enable_selective_load(*, serve: bool = False) -> None:
    """Hold back plugins nothing readied uses, in THIS process.

    The snapshot worker installs the filter at its first build's
    :func:`admit_for_toolsets`. The serve (``serve=True``) installs it now, before
    anything discovers, with no toolsets admitted, and keeps every platform plugin.
    """

    from hermes_cli import plugins as plugin_mod

    with _lock:
        _state["enabled"] = True
        if serve:
            _state["platforms"] = True
        install = serve and _state["toolsets"] is None
        if install:
            _state["toolsets"] = frozenset()
            _state["generation"] += 1
    _start_live_recording()
    if install:
        plugin_mod.set_plugin_load_filter(_admits)
        _log_receipt("install")


def _sync_active_manager() -> None:
    """Load into the active home's manager what the filter admits now and it has not loaded."""

    from hermes_cli import plugins as plugin_mod
    from hermes_constants import get_hermes_home

    manager = plugin_mod.get_plugin_manager()
    home = _home_key(getattr(manager, "home_path", None) or get_hermes_home())
    with _lock:
        generation, every = _state["generation"], _state["all"]
        toolsets, platforms = _state["toolsets"] or frozenset(), _state["platforms"]
        if _synced.get(manager) == generation:
            return
        _synced[manager] = generation
        held = _held.get(home, {})
        # Only a plugin this home's discovery held can be newly admitted: no
        # rescan when the widening reaches none of them.
        if not any(every or _row_needed(row, toolsets, platforms) for row in held.values()):
            return
        _held.pop(home, None)  # the load below gates every held plugin again
    if getattr(manager, "_discovered", False):
        # MUTATION: skip this load and test_plugin_uses' "a newly needed plugin
        # is loaded once, beside the ones already loaded" reddens.
        manager.load_admitted()


def admit_for_toolsets(toolsets: Iterable[str] | None) -> None:
    """Admit the plugins agents with ``toolsets`` use (``None``: every toolset), and load them.

    A no-op outside a process that called :func:`enable_selective_load`.
    """

    from hermes_cli import plugins as plugin_mod

    with _lock:
        if not _state["enabled"]:
            return
    wanted = None if toolsets is None else member_toolsets(toolsets)
    if wanted is not None and wanted & EVERY_TOOLSET:
        wanted = None  # "all" / "*" resolve to every toolset
    with _lock:
        previous = _state["toolsets"]
        if _state["all"] or (wanted is not None and previous is not None and wanted <= previous):
            op = None
        else:
            if wanted is None:
                _state["all"] = True
            _state["toolsets"] = (wanted or frozenset()) if previous is None else previous | (wanted or frozenset())
            _state["generation"] += 1
            op = "all" if wanted is None else "install" if previous is None else "widen"
    if op is not None:
        plugin_mod.set_plugin_load_filter(_admits)
        _log_receipt(op)
    _sync_active_manager()


def held_toolsets() -> frozenset[str]:
    """The toolsets of the plugins the active home's discoveries held back (registered on load)."""

    from hermes_constants import get_hermes_home

    with _lock:
        rows = list(_held.get(_home_key(get_hermes_home()), {}).values())
    return frozenset(name for row in rows if row for name in row["toolsets"])


def admit_for_agents(agents: Iterable[Any]) -> None:
    """:func:`admit_for_toolsets` for the toolsets these agents' profiles declare."""

    from .persona_profiles import effective_toolsets

    admit_for_toolsets(name for agent in agents for name in effective_toolsets(agent))
