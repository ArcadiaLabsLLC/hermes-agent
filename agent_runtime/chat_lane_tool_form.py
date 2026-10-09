"""The chat lane's tool form: one owner of a persona chat actor's ``tools``.

Plan ``docs/agent-runtime-harness/planned/tool-form-one-owner-2026-10-08.md``. A persona
chat turn's ``tools[]`` is derived ONCE, here, from the lane's raw definitions, the
constructor's post-build extras and the persona's defer list (``chat_lane_defer_tools``),
through the one assembly upstream's tool search runs (``assemble_tool_defs``) — at
construction (:func:`apply_chat_lane_defer`, from ``profile_runner.runner._default_agent_factory``)
and before every turn's first request (:func:`settle_turn_tool_form`, from the
eternia-harness ``pre_llm_call`` hook). The bridge (``tool_search``'s listing and count) is
re-derived from the current catalog, never frozen to the built bytes: the chats of one
instance share one prefix whatever catalog their actor was built on.

The raw read and the assembly are memoized per process on what they read — the registry's
CONTENT (:func:`agent_runtime.chat_lane_bundle.registry_content_revision`), the actor's
toolsets, the persona's names, the context window, the config file and the Launcher link —
never on ``registry.generation``, which MCP admission moves twice a turn while leaving the
registry as it found it — plus THIS run's admitted MCP tools by content
(:func:`admitted_mcp_tools`). A warm turn whose inputs did not move costs one byte compare.
The runner's factory switches upstream's between-turns MCP refresh off for every actor it
builds (``agent._skip_mcp_refresh``); the owner is what lands an admitted scope on a reused
actor (``adopt_late_connections`` still runs in upstream's slot, ahead of the flag).

The form is published only when its bytes moved, the run's block pruned in the same
publish, and the session pin (``tools.mcp_tool_agent.persist_agent_tool_names``) stores
exactly that form: the pre-brief ``request["tools"]`` of the turn.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Any, Iterable

from agent_runtime.chat_lane_defer import AGENT_DEFER_ATTR
from agent_runtime.tool_surface import AGENT_SURFACE_ATTR
from agent_runtime.tool_blocks import _tool_name as _def_name

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: :data:`AGENT_DEFER_ATTR` (``chat_lane_defer``) carries the persona's defer set from
#: construction to its turns; its presence is also the owner's admission: only an actor the
#: runner's factory built is settled.
#: Every name a raw read of this actor's lane produced. A name that leaves the read
#: (deregistered, out of scope) is dropped, never mistaken for a constructor-appended extra.
_RAW_NAMES_ATTR = "_chat_lane_raw_names"
#: ``(memo key, bytes of agent.tools as settled)``: the warm turn's one compare.
_SETTLED_ATTR = "_chat_lane_tool_form_settled"
#: The last settle's :class:`ToolFormReceipt` (tests and diagnosis read it).
RECEIPT_ATTR = "_chat_lane_tool_form_receipt"

_MEMO_LIMIT = 64
_RAW_MEMO: "OrderedDict[tuple, list]" = OrderedDict()
_FORM_MEMO: "OrderedDict[tuple, list]" = OrderedDict()


@dataclass(frozen=True)
class ToolFormReceipt:
    """One settle. ``source``: ``unchanged`` (nothing read, assembled or published), ``memo``
    (published from the memo, no read, no assembly) or ``rebuilt`` (read and/or assembled,
    published or not)."""

    source: str
    published: bool
    pin_written: bool
    names: int
    json_bytes: int
    admitted: int


def clear_tool_form_memo() -> None:
    """Drop the per-process memo (tests; an explicit catalog reset)."""

    _RAW_MEMO.clear()
    _FORM_MEMO.clear()


def _dump(defs: Any) -> str:
    return json.dumps(defs, ensure_ascii=False, separators=(",", ":"), default=str)


def _remember(memo: OrderedDict, key: tuple, value: list) -> None:
    memo[key] = value
    memo.move_to_end(key)
    while len(memo) > _MEMO_LIMIT:
        memo.popitem(last=False)


def _config_signature() -> Any:
    """config.yaml's stat signature: the dynamic-schema input upstream's memo also keys on."""

    try:
        from hermes_cli.config import get_config_path
        from utils import file_signature

        return file_signature(get_config_path().stat())
    except Exception:  # noqa: BLE001 - no config file is a stable input too
        return None


def admitted_mcp_tools(agent: Any) -> tuple:
    """This run's admitted MCP tools as the actor sees them: ``(name, toolset, schema digest)``
    of every registered ``mcp-*`` tool inside the actor's toolsets, sorted. Another run's scope
    (a toolset this actor was not scoped to) is not in it, so its churn moves nothing here."""

    from tools.registry import registry

    from .mcp_admission.vocabulary import _MCP_TOOLSET_PREFIX

    enabled = getattr(agent, "enabled_toolsets", None)
    disabled = set(getattr(agent, "disabled_toolsets", None) or ())
    scope = None
    if enabled is not None:
        aliases = registry.get_registered_toolset_aliases()
        scope = set(enabled) | {aliases[t] for t in enabled if t in aliases}
    rows = []
    for entry in registry.get_all_entries():
        toolset = str(entry.toolset)
        if not toolset.startswith(_MCP_TOOLSET_PREFIX) or toolset in disabled:
            continue
        if scope is not None and toolset not in scope:
            continue
        schema = hashlib.sha256(_dump(entry.schema).encode("utf-8")).hexdigest()
        rows.append((str(entry.name), toolset, schema))
    return tuple(sorted(rows))


def _form_key(agent: Any, names: frozenset[str], base: Any) -> tuple:
    """What the raw read and the assembly read, by content."""

    from agent_runtime.chat_lane_bundle import registry_content_revision
    from agent_runtime.launcher_app_functions import app_function_tool_scope
    from tools.registry import registry

    enabled = getattr(agent, "enabled_toolsets", None)
    disabled = getattr(agent, "disabled_toolsets", None)
    compressor = getattr(agent, "context_compressor", None)
    return (
        registry_content_revision(),
        registry.current_scope_key(),
        tuple(sorted(enabled)) if enabled is not None else None,
        tuple(sorted(disabled)) if disabled else None,
        tuple(sorted(names)),
        int(getattr(compressor, "context_length", 0) or 0),
        repr(base),
        _config_signature(),
        app_function_tool_scope(),
        admitted_mcp_tools(agent),
    )


def _read_raw(agent: Any) -> list:
    import model_tools

    return list(model_tools.get_tool_definitions(
        enabled_toolsets=getattr(agent, "enabled_toolsets", None),
        disabled_toolsets=getattr(agent, "disabled_toolsets", None),
        quiet_mode=True,
        skip_tool_search_assembly=True,
    ) or [])


def _assemble(agent: Any, raw: list, extras: list, names: frozenset[str], base: Any, context_length: int):
    """The ONE assembly, and its account: upstream's tool search over raw + extras with the
    persona's names deferred, through :func:`agent_runtime.tool_surface.assemble_surface` —
    the function the ``persona tool-diff`` preview calls too, so the two are one answer."""

    from agent_runtime.tool_surface import assemble_surface

    return assemble_surface(
        raw, enabled_toolsets=getattr(agent, "enabled_toolsets", None),
        disabled_toolsets=getattr(agent, "disabled_toolsets", None), defer_tools=names,
        context_length=context_length or None, tool_search_config=base, extras=extras,
    )


def _derive(agent: Any, key: tuple, names: frozenset[str], base: Any) -> tuple[Any, str]:
    """The surface (whose ``tool_defs`` is the form) for ``key`` and this actor's extras;
    ``rebuilt`` when anything was read or assembled."""

    from tools.tool_search import BRIDGE_TOOL_NAMES

    source = "memo"
    raw = _RAW_MEMO.get(key)
    if raw is None:
        raw = _read_raw(agent)
        _remember(_RAW_MEMO, key, raw)
        source = "rebuilt"
    seen = frozenset(getattr(agent, _RAW_NAMES_ATTR, None) or ()) | {_def_name(td) for td in raw}
    setattr(agent, _RAW_NAMES_ATTR, seen)
    extras = [td for td in agent.tools
              if _def_name(td) not in seen and _def_name(td) not in BRIDGE_TOOL_NAMES]
    form_key = (key, hashlib.sha256(_dump(extras).encode("utf-8")).hexdigest())
    surface = _FORM_MEMO.get(form_key)
    if surface is None:
        compressor = getattr(agent, "context_compressor", None)
        surface = _assemble(agent, raw, extras, names, base, int(getattr(compressor, "context_length", 0) or 0))
        _remember(_FORM_MEMO, form_key, surface)
        source = "rebuilt"
    return surface, source


def _settle(agent: Any, names: frozenset[str], *, blocked: Iterable[str] | None, pin: bool) -> ToolFormReceipt:
    from tools.tool_search import load_config

    base = load_config()
    key = _form_key(agent, names, base)
    current = _dump(agent.tools)
    if getattr(agent, _SETTLED_ATTR, None) == (key, current):
        return ToolFormReceipt("unchanged", False, False, len(agent.tools), len(current.encode("utf-8")),
                               len(admitted_mcp_tools(agent)))
    surface, source = _derive(agent, key, names, base)
    form = list(surface.tool_defs)
    block = frozenset(str(n) for n in (blocked or ()))
    candidate = [td for td in form if _def_name(td) not in block] if block else form
    wire = _dump(candidate)
    published = wire != current
    if published:
        # One write of the pair, on the turn's own thread: with upstream's refresh off for the
        # lane there is no concurrent writer.
        tools = copy.deepcopy(candidate)
        agent.tools = tools
        agent.valid_tool_names = {_def_name(td) for td in tools if _def_name(td)}
        # The executor caches the bridge's reachable set per agent.
        if hasattr(agent, "_tool_search_scope_cache"):
            agent._tool_search_scope_cache = None
    elif source == "memo":
        source = "unchanged"  # a rebuild that landed on the same bytes still says so
    if block:
        from agent_runtime.tool_blocks import prune_agent_tools

        prune_agent_tools(agent, block)  # valid names and the kanban guidance; tools already pruned
    pin_written = False
    if published and pin:
        import tools.mcp_tool_agent as mcp_tool_agent

        mcp_tool_agent.persist_agent_tool_names(agent)
        pin_written = True
    setattr(agent, _SETTLED_ATTR, (key, wire))
    # The surface receipt (toolvis slice 4): every name this form left off the wire, and why.
    # Set with the form, so an ``unchanged`` settle keeps the receipt of the form it kept.
    setattr(agent, AGENT_SURFACE_ATTR, surface.with_block(block).receipt())
    return ToolFormReceipt(source, published, pin_written, len(candidate), len(wire.encode("utf-8")),
                           len(admitted_mcp_tools(agent)))


def settle_turn_tool_form(
    agent: Any, *, blocked: Iterable[str] | None = None, pin: bool = True,
) -> ToolFormReceipt | None:
    """Produce the turn's ``tools`` once; publish and pin only when the bytes moved.

    A no-op (``None``) for an actor the runner's factory did not build (no
    :data:`AGENT_DEFER_ATTR`). Never raises: a fault leaves the actor's form standing.
    """

    if not hasattr(agent, AGENT_DEFER_ATTR) or not getattr(agent, "tools", None):
        return None
    names = frozenset(getattr(agent, AGENT_DEFER_ATTR) or ())
    try:
        receipt = _settle(agent, names, blocked=blocked, pin=pin)
    except Exception as exc:  # noqa: BLE001 - a form settle is a cost cut; never fail a turn over it
        logger.warning("tool form settle skipped; the actor's form stands", exc_info=True)
        _record_degraded(agent, exc)
        return None
    setattr(agent, RECEIPT_ATTR, receipt)
    if pin:
        logger.info(
            "tool_form_receipt turn=%s source=%s publishes=%d pin_written=%d names=%d json_bytes=%d admitted=%d",
            getattr(agent, "_current_turn_id", "") or "", receipt.source, int(receipt.published),
            int(receipt.pin_written), receipt.names, receipt.json_bytes, receipt.admitted,
        )
    return receipt


def _record_degraded(agent: Any, exc: BaseException) -> None:
    """The fault is a receipt row, not only a WARNING: the form that stands, eager, and why."""

    from agent_runtime.tool_surface import ToolSurface

    try:
        surface = ToolSurface.constructor_form(
            list(getattr(agent, "tools", None) or ()),
            enabled_toolsets=getattr(agent, "enabled_toolsets", None),
            degraded=(f"assembly:{type(exc).__name__}",),
        )
        setattr(agent, AGENT_SURFACE_ATTR, surface.receipt())
    except Exception:  # noqa: BLE001 - the WARNING above already stands
        logger.debug("tool surface: degraded receipt not recorded", exc_info=True)


def apply_chat_lane_defer(
    agent: Any, defer_tools: Iterable[str] | None, *, blocked: Iterable[str] | None = None,
) -> bool:
    """Construction: bind the persona's defer set and settle the form; True when it changed.

    With no list the constructor's (profile-wide) form IS the settled form for this key --
    upstream's own assembly of the same catalog -- recorded without a read, so a warm first
    turn costs one compare (the prewarm owns the constructor's read; a read on the turn
    imports what the prewarm already warmed). The run's block is pruned in the same settle.
    The pin is the turn's, never the constructor's.
    """

    names = frozenset(str(n).strip() for n in (defer_tools or ()) if str(n).strip())
    setattr(agent, AGENT_DEFER_ATTR, names)
    if names:
        receipt = settle_turn_tool_form(agent, blocked=blocked, pin=False)
        return bool(receipt and receipt.published)
    if not getattr(agent, "tools", None):
        return False
    try:
        from agent_runtime.tool_blocks import prune_agent_tools
        from tools.tool_search import load_config

        prune_agent_tools(agent, blocked)
        setattr(agent, _SETTLED_ATTR, (_form_key(agent, names, load_config()), _dump(agent.tools)))
    except Exception:  # noqa: BLE001 - the first turn settles it instead
        logger.debug("tool form: constructor form not recorded", exc_info=True)
    return False


__all__ = [
    "AGENT_DEFER_ATTR",
    "RECEIPT_ATTR",
    "ToolFormReceipt",
    "admitted_mcp_tools",
    "apply_chat_lane_defer",
    "clear_tool_form_memo",
    "settle_turn_tool_form",
]
