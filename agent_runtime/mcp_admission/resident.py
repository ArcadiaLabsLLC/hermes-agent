"""The resident registry scope (design sweep D1.01, owner ruling 2026-10-10).

An admitted server's registry scope lives as long as its transport session and its
admission content, not as long as one run. R2 tore the scope down after every run:
N ``registry.deregister`` calls, then N ``registry.register`` calls on the next run off the
very session the transport had kept warm — 10-11 ms of ``mcp_admission_ms`` and a 2N move of
``registry.generation``, which drops upstream's tool-definitions memo
(``model_tools._tool_defs_cache_key``) on every reused actor's turn (D1.02, 202-215 ms per miss).

Isolation between personas was never the teardown: it is
:func:`agent_runtime.mcp_admission.resolve.scope_toolsets_to_admission`, which strips every
``mcp-*`` toolset a run was not admitted before ``get_tool_definitions`` runs. A resident scope
is therefore the state upstream's own ``chat`` / ``gateway`` lanes already run in.

What a run does now: bind its :class:`McpCallBudget` into the scope's :class:`BudgetSlot`, which
every metered handler reads AT CALL TIME; on the way out, clear the slot and keep the scope.
``_WORKDIR_LOCK`` serialises runs, so one slot per scope is enough — never a stack.

Every read and write of :data:`_RESIDENT_SCOPES` happens under the admission mutex
(``registration._ADMISSION_LOCK``); the slot carries its own lock because tool threads read it.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .vocabulary import _MCP_TOOLSET_PREFIX, logger

__layer__ = "stores"

#: Attribute a metered handler carries naming the slot it reads. A registered handler whose slot
#: is not the resident scope's own was re-registered under it (an upstream ``list_changed``
#: repave, another profile's admission of the same server): the scope is no longer the one
#: this memo recorded.
SLOT_ATTR = "_mcp_admission_budget_slot"


class BudgetSlot:
    """The call budget a resident scope's metered handlers read at call time.

    Bound by the run that admitted the scope, cleared by that run's release. A dispatch that
    finds it empty belongs to no admitted run and is refused (``registration._metered_handler``).
    """

    __slots__ = ("_lock", "_budget", "_on_exhausted")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._budget: Any = None
        self._on_exhausted: Callable[..., None] | None = None

    def bind(self, budget: Any, on_exhausted: Callable[..., None] | None) -> None:
        with self._lock:
            self._budget = budget
            self._on_exhausted = on_exhausted

    def clear(self) -> None:
        with self._lock:
            self._budget = None
            self._on_exhausted = None

    def current(self) -> tuple[Any, Callable[..., None] | None]:
        with self._lock:
            return self._budget, self._on_exhausted


@dataclass(slots=True)
class ResidentScope:
    """One admitted server's registered tools, kept between runs."""

    home_key: str
    server: str
    #: Digest of the admitted server config, ``tools`` filter included: a narrower admission
    #: of the same server must not inherit a wider registered surface.
    filter_revision: str
    tool_names: frozenset[str]
    slot: BudgetSlot


#: ``(hermes_home_key(), server) -> ResidentScope``. Keyed by home because MCP tools may live in
#: a profile overlay of the registry and two profiles may declare the same server name.
_RESIDENT_SCOPES: dict[tuple[str, str], ResidentScope] = {}


def _home_key() -> str:
    from hermes_constants import hermes_home_key

    return hermes_home_key()


def config_revision(config: Mapping[str, Any] | None) -> str:
    """Stable digest of one admitted server config (secrets never leave it: digest only)."""

    raw = json.dumps(dict(config or {}), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _registry():
    from tools.registry import registry

    return registry


def registered_tool_names(server: str) -> frozenset[str]:
    """The tools of ``mcp-<server>`` the registry holds now, from the current scope."""

    try:
        return frozenset(_registry().get_tool_names_for_toolset(f"{_MCP_TOOLSET_PREFIX}{server}") or ())
    except Exception:  # pragma: no cover - registry is always importable in-process
        logger.debug("MCP admission could not read %r's registered tools", server, exc_info=True)
        return frozenset()


def _metered_by(registry: Any, tool_names: Iterable[str], slot: BudgetSlot) -> bool:
    for name in tool_names:
        entry = registry.get_entry(name)
        if entry is None or getattr(getattr(entry, "handler", None), SLOT_ATTR, None) is not slot:
            return False
    return True


def _invalid_reason(scope: ResidentScope, config: Mapping[str, Any] | None) -> str | None:
    """Why ``scope`` no longer stands for ``config``'s admission; ``None`` when it does."""

    if config is not None and scope.filter_revision != config_revision(config):
        return "admission content changed"
    names = registered_tool_names(scope.server)
    if names != scope.tool_names:
        return "registered tools changed"
    if not _metered_by(_registry(), names, scope.slot):
        return "a tool was re-registered outside the scope"
    return None


def partition_admission(
    servers: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, ResidentScope], dict[str, Mapping[str, Any]]]:
    """Split an admitted set into ``(reused, to_register)``.

    A server with a STALE resident scope has that scope's tools deregistered here, before the
    registrar runs: upstream's ``_register_server_tools`` registers on top of what is there, so
    a narrower filter would otherwise keep the wider surface (R2's acceptance case).
    """

    reused: dict[str, ResidentScope] = {}
    fresh: dict[str, Mapping[str, Any]] = {}
    home = _home_key()
    for name, config in servers.items():
        scope = _RESIDENT_SCOPES.get((home, name))
        reason = None if scope is None else _invalid_reason(scope, config)
        if scope is not None and reason is None:
            reused[name] = scope
            continue
        if scope is not None:
            logger.info("MCP admission re-registers %r: %s", name, reason)
            _RESIDENT_SCOPES.pop((home, name), None)
            scope.slot.clear()
            deregister_server_tools(name)
        fresh[name] = config
    return reused, fresh


def record_resident_scope(server: str, config: Mapping[str, Any] | None, slot: BudgetSlot) -> None:
    """Remember the scope this admission registered; an empty one is not remembered."""

    names = registered_tool_names(server)
    key = (_home_key(), server)
    if not names:
        _RESIDENT_SCOPES.pop(key, None)
        return
    _RESIDENT_SCOPES[key] = ResidentScope(
        home_key=key[0],
        server=server,
        filter_revision=config_revision(config),
        tool_names=names,
        slot=slot,
    )


def release_slots(servers: Iterable[str]) -> None:
    """Clear the budget slots of ``servers``' resident scopes in the current home."""

    home = _home_key()
    for name in servers:
        scope = _RESIDENT_SCOPES.get((home, name))
        if scope is not None:
            scope.slot.clear()


def forget(servers: Iterable[str]) -> None:
    """Drop the memo entries for ``servers`` in the current home (their tools are going)."""

    home = _home_key()
    for name in servers:
        scope = _RESIDENT_SCOPES.pop((home, name), None)
        if scope is not None:
            scope.slot.clear()


def deregister_server_tools(server: str, registry: Any = None) -> list[str]:
    """Deregister every tool of ``mcp-<server>`` visible from the current scope; raises on a
    registry fault (the callers type it)."""

    registry = registry if registry is not None else _registry()
    removed: list[str] = []
    for tool_name in list(registry.get_tool_names_for_toolset(f"{_MCP_TOOLSET_PREFIX}{server}") or []):
        registry.deregister(tool_name)
        removed.append(tool_name)
    return removed
