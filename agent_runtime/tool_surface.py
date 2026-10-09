"""The cost layer: which schemas RIDE a turn, and for every name that does not, the one rule that moved it.

Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md`` §2(b),
slice 3. The capability authority (declaration, permission, admission — ``tool_visibility``)
answers "what may this persona do"; this module answers "what does the provider see", and it
may only DEFER or DROP a name the capability already holds, never add one.

:func:`compute_tool_surface` runs the chain the agent factory runs — upstream's
``model_tools.get_tool_definitions(skip_tool_search_assembly=True)`` for availability, upstream's
``tools.tool_search.assemble_tool_defs`` with the persona's defer for the split, the run's block —
and partitions every requested name into exactly one :class:`ToolDisposition`
(``eager | deferred | unavailable | blocked``) with one :class:`DispositionReason`. The reason
is derived by ASKING upstream's classifier (``is_deferrable_tool_name``) with controlled
arguments, never by re-spelling its ladder.

One function, two callers on one input: the factory (``chat_lane_defer.apply_chat_lane_defer``,
which attaches :meth:`ToolSurface.receipt` to the agent) and the preview (``persona tool-diff``,
from the chat-lane bundle's ``tool_contract``). That is what makes the preview and the wire
one answer instead of two equal ones.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping

from agent_runtime.tool_blocks import tool_definition_name as _def_name

__layer__ = "policy"

#: The agent attribute that carries the surface receipt from construction to the turn's readers.
AGENT_SURFACE_ATTR = "_hermes_tool_surface_receipt"
TOOL_SURFACE_SCHEMA_VERSION = 1

STATE_EAGER = "eager"
STATE_DEFERRED = "deferred"
STATE_UNAVAILABLE = "unavailable"
STATE_BLOCKED = "blocked"
STATES = (STATE_EAGER, STATE_DEFERRED, STATE_UNAVAILABLE, STATE_BLOCKED)


class DispositionReason(str, Enum):
    """Why a name is where it is. The value IS the wire spelling (the preview's literals kept)."""

    # cost: deferred behind the tool_search bridge
    PERSONA_DEFER = "persona_defer"
    CURATED_DEFAULT_DEFER = "curated_default_defer"
    MCP_DEFER = "mcp_defer"
    NON_CORE_RULE_DEFER = "non_core_rule_defer"
    # eager by a decision, not by default
    PROMOTED_EAGER = "promoted_eager"
    TOOL_SEARCH_OFF = "tool_search_off"
    # availability
    CHECK_FN_UNAVAILABLE = "check_fn_unavailable"
    BACKEND_SWAP = "backend_swap"
    # the block (the preview's ladder; same spellings on the wire)
    REGISTRY_HYGIENE = "registry_hygiene"
    PERSONA_SAFETY_POLICY = "persona_safety_policy"
    ROLE_POLICY = "role_policy"
    TURN_RUNTIME_BLOCK = "turn_runtime_block"
    SESSION_TOOL_POLICY = "session_tool_policy"
    SESSION_TOOLSET_POLICY = "session_toolset_policy"
    PERMISSION_MODE = "permission_mode"
    CHAT_LANE_COST_TOOLSET = "chat_lane_cost_toolset"
    CHAT_LANE_COST_TOOL = "chat_lane_cost_tool"
    ADMISSION_NOT_ADMITTED = "admission_not_admitted"


#: Where an operator changes each deferral. ``non_core_rule_defer`` has none yet: the fork has not
#: decided its own harness tools' eager set (ruling R3 — they stay deferred until call counts are
#: measured), so there is no key to name.
_RESTORABLE_VIA: Mapping[DispositionReason, str] = {
    DispositionReason.PERSONA_DEFER: "agent_runtime.personas.<persona>.chat_lane_defer_tools",
    DispositionReason.CURATED_DEFAULT_DEFER: "tools.tool_search.defer",
    DispositionReason.MCP_DEFER: "tools.tool_search.never_defer",
}


def blocked_reason(
    name: str,
    *,
    requested_denies: Iterable[str] = (),
    registry_hygiene_denies: Iterable[str] = (),
    role_denies: Iterable[str] = (),
    persona_denies: Iterable[str] = (),
) -> DispositionReason:
    """The block's reason ladder — ONE spelling, read by the preview and the surface alike."""

    if name in set(requested_denies):
        return DispositionReason.TURN_RUNTIME_BLOCK
    if name in set(registry_hygiene_denies):
        return DispositionReason.REGISTRY_HYGIENE
    if name in set(role_denies):
        return DispositionReason.ROLE_POLICY
    if name in set(persona_denies):
        return DispositionReason.PERSONA_SAFETY_POLICY
    return DispositionReason.SESSION_TOOL_POLICY


@dataclass(frozen=True, slots=True)
class ToolDisposition:
    name: str
    state: str
    reason: DispositionReason | None = None

    def row(self) -> dict[str, Any]:
        row: dict[str, Any] = {"reason": self.reason.value if self.reason is not None else None}
        via = _RESTORABLE_VIA.get(self.reason) if self.reason is not None else None
        if via:
            row["restorable_via"] = via
        return row


@dataclass(frozen=True)
class ToolSurface:
    """Every requested name in exactly one state; the bridge listed apart (it is the cost layer's own)."""

    enabled_toolsets: tuple[str, ...]
    dispositions: tuple[ToolDisposition, ...]
    bridge: tuple[str, ...] = ()
    degraded: tuple[str, ...] = ()
    tool_search: str = ""
    #: The definitions to publish as ``agent.tools`` (assembled, before the block's prune).
    #: Never in the receipt — schema text is not observability material.
    tool_defs: tuple[dict[str, Any], ...] = field(default=(), repr=False, compare=False)

    def names(self, state: str) -> list[str]:
        return sorted(d.name for d in self.dispositions if d.state == state)

    @property
    def eager(self) -> list[str]:
        return self.names(STATE_EAGER)

    @property
    def deferred(self) -> list[str]:
        return self.names(STATE_DEFERRED)

    @property
    def unavailable(self) -> list[str]:
        return self.names(STATE_UNAVAILABLE)

    @property
    def blocked(self) -> list[str]:
        return self.names(STATE_BLOCKED)

    def by_name(self) -> dict[str, ToolDisposition]:
        return {d.name: d for d in self.dispositions}

    @property
    def resolution_id(self) -> str:
        material = {
            "enabled_toolsets": sorted(self.enabled_toolsets),
            "bridge": sorted(self.bridge),
            **{
                state: sorted(
                    (d.name, d.reason.value if d.reason is not None else None)
                    for d in self.dispositions if d.state == state
                )
                for state in STATES
            },
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"toolsurf_{hashlib.sha256(encoded).hexdigest()[:16]}"

    def receipt(self) -> dict[str, Any]:
        """Schema v1 (plan §2c): names, reasons and counts — never a schema body."""

        rows = {state: {} for state in STATES}
        for d in sorted(self.dispositions, key=lambda item: item.name):
            rows[d.state][d.name] = d.row()
        counts = {state: len(rows[state]) for state in STATES}
        counts["bridge"] = len(self.bridge)
        counts["callable_by_name"] = counts[STATE_EAGER] + counts[STATE_DEFERRED] + counts[STATE_UNAVAILABLE]
        return {
            "schema_version": TOOL_SURFACE_SCHEMA_VERSION,
            "resolution_id": self.resolution_id,
            "enabled_toolsets": list(self.enabled_toolsets),
            "tool_search": self.tool_search,
            **rows,
            "bridge": sorted(self.bridge),
            "counts": counts,
            "degraded": list(self.degraded),
        }

    def with_block(
        self, blocked_tool_names: Iterable[str] = (), *, admission_stripped_toolsets: Iterable[str] = (),
    ) -> "ToolSurface":
        """This surface with the run's block applied: a blocked name leaves every other state."""

        from .personas import PERSONA_BLOCKED_TOOLS, REGISTRY_HYGIENE_BLOCKED_TOOLS

        block = frozenset(str(n) for n in blocked_tool_names or () if n)
        rows = [
            ToolDisposition(d.name, STATE_BLOCKED, blocked_reason(
                d.name, registry_hygiene_denies=REGISTRY_HYGIENE_BLOCKED_TOOLS,
                persona_denies=PERSONA_BLOCKED_TOOLS,
            )) if d.name in block else d
            for d in self.dispositions
        ]
        known = {d.name for d in rows}
        for toolset in admission_stripped_toolsets or ():
            for name in sorted(requested_tool_names([str(toolset)]) - known):
                rows.append(ToolDisposition(name, STATE_BLOCKED, DispositionReason.ADMISSION_NOT_ADMITTED))
                known.add(name)
        return replace(self, dispositions=tuple(rows))

    @classmethod
    def constructor_form(
        cls, tool_defs: Iterable[dict[str, Any]], *, enabled_toolsets: Iterable[str] | None,
        degraded: Iterable[str],
    ) -> "ToolSurface":
        """The surface of a list nobody re-assembled (the fault path): what stands, eager, recorded."""

        from tools.tool_search_catalog import BRIDGE_TOOL_NAMES

        names = [_def_name(td) for td in tool_defs]
        return cls(
            enabled_toolsets=tuple(enabled_toolsets or ()),
            dispositions=tuple(
                ToolDisposition(n, STATE_EAGER) for n in dict.fromkeys(names)
                if n and n not in BRIDGE_TOOL_NAMES
            ),
            bridge=tuple(sorted({n for n in names if n in BRIDGE_TOOL_NAMES})),
            degraded=tuple(degraded),
        )


def _registered_toolset(name: str) -> str | None:
    """The toolset a tool REGISTERS into (manifest for builtins, the live registry otherwise)."""

    from tools.registry import registry
    from tools.toolset_manifest import builtin_toolset_for_tool

    toolset = builtin_toolset_for_tool(name)
    if toolset is None:
        try:
            toolset = registry.get_toolset_for_tool(name)
        except Exception:
            toolset = None
    return str(toolset) if toolset else None


def _toolset_closure(enabled: Iterable[str]) -> set[str]:
    """The enabled toolsets and every toolset they include, transitively."""

    import toolsets

    seen: set[str] = set()
    stack = [str(name) for name in enabled]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        spec = toolsets.get_toolset(name) or {}
        stack.extend(str(child) for child in spec.get("includes") or ())
    return seen


def requested_tool_names(
    enabled_toolsets: Iterable[str] | None, disabled_toolsets: Iterable[str] | None = None
) -> set[str]:
    """The names the toolset selection REQUESTS, before any check_fn — upstream's definitions.

    ``toolsets.resolve_toolset`` is the definition ``model_tools`` selects by. The preview's
    ``tool_visibility._cached_tool_names_for_toolsets`` answers a different question (which tools
    REGISTER into a toolset) and so cannot see ``browser_exec``, which upstream's ``browser``
    toolset lists by name while it registers into ``browser-use`` (note §5 item 2).
    """

    import toolsets
    from agent_runtime.harness_toolset import ensure_harness_core

    ensure_harness_core()
    names: set[str] = set()
    for toolset in (["all"] if enabled_toolsets is None else list(enabled_toolsets)):
        names.update(toolsets.resolve_toolset(str(toolset)))
    for toolset in disabled_toolsets or ():
        # A bundle re-lists the core without owning it; disabling one removes its delta only
        # (upstream's own helper for exactly this — ``model_tools._apply_toolset_selection``).
        spec = toolsets.get_toolset(str(toolset)) or {}
        if str(toolset).startswith("hermes-") or spec.get("posture"):
            names.difference_update(toolsets.bundle_non_core_tools(str(toolset)))
        else:
            names.difference_update(toolsets.resolve_toolset(str(toolset)))
    try:
        for toolset in toolsets.profile_role_toolsets()[1]:
            names.difference_update(toolsets.resolve_toolset(toolset))
    except Exception:  # pragma: no cover - a profile meta read fault reserves nothing
        pass
    return names


def _family(toolset: str | None) -> str:
    return re.split(r"[-_]", str(toolset or ""), maxsplit=1)[0]


def _swap_families(available: set[str], closure: set[str]) -> set[str]:
    """Toolset families an available name entered from OUTSIDE the enabled closure — listed by
    name in a toolset it does not register into (``browser_exec``: upstream's ``browser`` toolset
    names it, it registers into ``browser-use``). That is what a backend swap looks like."""

    families: set[str] = set()
    for name in available:
        toolset = _registered_toolset(name)
        if toolset and toolset not in closure:
            families.add(_family(toolset))
    families.discard("")
    return families


def _unavailable_reason(name: str, *, swap_families: set[str]) -> DispositionReason:
    """``backend_swap`` when a swap target of this name's toolset family is on the surface;
    otherwise its check_fn said no."""

    if _family(_registered_toolset(name)) in swap_families:
        return DispositionReason.BACKEND_SWAP
    return DispositionReason.CHECK_FN_UNAVAILABLE


def _deferred_reason(
    name: str, *, curated: frozenset, persona: frozenset, config: Any
) -> DispositionReason | None:
    """Ask upstream's classifier which rule moved ``name``: the rule alone, the curated list, the
    persona's list — the most structural answer first (removing the persona's name would not
    un-defer a tool the rule defers)."""

    from tools.tool_search import is_deferrable_tool_name

    if is_deferrable_tool_name(name, frozenset(), config=config):
        return (DispositionReason.MCP_DEFER
                if str(_registered_toolset(name) or "").startswith("mcp-")
                else DispositionReason.NON_CORE_RULE_DEFER)
    if name in curated and is_deferrable_tool_name(name, curated, config=config):
        return DispositionReason.CURATED_DEFAULT_DEFER
    if name in persona and is_deferrable_tool_name(name, persona, config=config):
        return DispositionReason.PERSONA_DEFER
    return None


def _partition(
    requested: set[str], *, available: set[str], wire: set[str], closure: set[str],
    promoted: frozenset, off: bool, curated: frozenset, persona: frozenset, config: Any,
) -> list[ToolDisposition]:
    """Every requested or available name in exactly one state, with the rule that put it there."""

    from tools.tool_search import BRIDGE_TOOL_NAMES

    swap_families = _swap_families(available, closure)
    dispositions: list[ToolDisposition] = []
    for name in sorted((requested | available) - BRIDGE_TOOL_NAMES):
        if name not in available:
            dispositions.append(ToolDisposition(
                name, STATE_UNAVAILABLE, _unavailable_reason(name, swap_families=swap_families)))
        elif name in wire:
            reason = None
            if name in promoted:
                reason = DispositionReason.PROMOTED_EAGER
            elif off and _deferred_reason(name, curated=curated, persona=persona, config=config):
                reason = DispositionReason.TOOL_SEARCH_OFF
            dispositions.append(ToolDisposition(name, STATE_EAGER, reason))
        else:
            dispositions.append(ToolDisposition(
                name, STATE_DEFERRED,
                _deferred_reason(name, curated=curated, persona=persona, config=config)))
    return dispositions


def assemble_surface(
    raw: Iterable[dict[str, Any]],
    *,
    enabled_toolsets: Iterable[str] | None,
    disabled_toolsets: Iterable[str] | None = None,
    defer_tools: Iterable[str] = (),
    context_length: int | None = None,
    tool_search_config: Any = None,
    extras: Iterable[dict[str, Any]] = (),
    extras_ride_eager: bool = False,
) -> ToolSurface:
    """The assembly and its account, over definitions already read: the ONE function both the
    tool form's owner (``chat_lane_tool_form``, which memoizes the read) and the preview
    (:func:`compute_tool_surface`) call. ``tool_defs`` is the form the owner publishes —
    upstream's ``assemble_tool_defs`` over raw + extras with the persona's names deferred, then
    ``ensure_tool_describe_present``; with ``tool_search.enabled: off``, raw + extras as they
    stand. The run's block is applied after (:meth:`ToolSurface.with_block`), as the owner prunes.
    ``extras_ride_eager`` is the CONSTRUCTOR's form (upstream assembles the lane's definitions and
    appends the post-build extras after it): the account of an actor the owner never re-assembled.
    """

    from tools.tool_search import BRIDGE_TOOL_NAMES, assemble_tool_defs, load_config
    from tools.tool_search_downstream import ensure_tool_describe_present, never_defer_tool_names

    raw = list(raw or ())
    enabled = None if enabled_toolsets is None else [str(name) for name in enabled_toolsets]
    disabled = [str(name) for name in disabled_toolsets or ()] or None
    base = tool_search_config or load_config()
    persona = frozenset(str(n).strip() for n in defer_tools or () if str(n).strip())
    curated = frozenset(base.effective_defer_tools)
    config = replace(base, defer_tools=curated | persona)
    off = base.enabled == "off"

    raw_names = {_def_name(td) for td in raw}
    extra_defs = [td for td in extras or () if _def_name(td) not in raw_names
                  and _def_name(td) not in BRIDGE_TOOL_NAMES]
    if off:
        tool_defs = raw + extra_defs
    else:
        assembled = raw if extras_ride_eager else raw + extra_defs
        assembly = assemble_tool_defs(assembled, context_length=context_length or None, config=config)
        tool_defs = ensure_tool_describe_present(assembly.tool_defs) + (extra_defs if extras_ride_eager else [])
    wire = {_def_name(td) for td in tool_defs}

    available = (raw_names | {_def_name(td) for td in extra_defs}) - BRIDGE_TOOL_NAMES
    degraded: tuple[str, ...] = ()
    try:
        dispositions = _partition(
            requested_tool_names(enabled, disabled), available=available, wire=wire,
            closure=_toolset_closure(enabled or ()), promoted=never_defer_tool_names(config),
            off=off, curated=curated, persona=persona, config=config,
        )
    except Exception as exc:  # noqa: BLE001 - the account never costs the form its cost cut
        # The form stands; the account says it could not be taken (``account:<Exc>``) and
        # reports what it does know, the wire, eager.
        dispositions = [ToolDisposition(n, STATE_EAGER) for n in sorted(wire - BRIDGE_TOOL_NAMES)]
        degraded = (f"account:{type(exc).__name__}",)
    return ToolSurface(
        enabled_toolsets=tuple(enabled or ()),
        dispositions=tuple(dispositions),
        bridge=tuple(sorted(wire & BRIDGE_TOOL_NAMES)),
        degraded=degraded,
        tool_search=str(base.enabled),
        tool_defs=tuple(tool_defs),
    )


def compute_tool_surface(
    *,
    enabled_toolsets: Iterable[str] | None,
    disabled_toolsets: Iterable[str] | None = None,
    blocked_tool_names: Iterable[str] = (),
    defer_tools: Iterable[str] = (),
    context_length: int | None = None,
    tool_search_config: Any = None,
    extras: Iterable[dict[str, Any]] = (),
    admission_stripped_toolsets: Iterable[str] = (),
) -> ToolSurface:
    """The surface one agent would ship, read from scratch: the preview's door (``persona
    tool-diff``). Raises on a fault; the preview reports it.

    ``admission_stripped_toolsets`` is the caller's ``mcp_admission.resolve.admission_strips``
    answer — this module is policy, admission is a store.
    """

    import model_tools

    enabled = None if enabled_toolsets is None else [str(name) for name in enabled_toolsets]
    disabled = [str(name) for name in disabled_toolsets or ()] or None
    raw = model_tools.get_tool_definitions(
        enabled_toolsets=enabled, disabled_toolsets=disabled, quiet_mode=True,
        skip_tool_search_assembly=True,
    ) or []
    return assemble_surface(
        raw, enabled_toolsets=enabled, disabled_toolsets=disabled, defer_tools=defer_tools,
        context_length=context_length, tool_search_config=tool_search_config, extras=extras,
    ).with_block(blocked_tool_names, admission_stripped_toolsets=admission_stripped_toolsets)


def not_computed(reason: str) -> dict[str, Any]:
    """The typed absence of a surface: a reader says WHY there is no account, never nothing."""

    return {"schema_version": TOOL_SURFACE_SCHEMA_VERSION, "state": "not_computed", "reason": str(reason)}


def unaliased_wire_names(wire_receipt: Mapping[str, Any] | None) -> list[str]:
    """The wire receipt's names with the transport's bridge alias reversed (note §5 item 1).

    The ``llm_request`` middleware sees the request AFTER the transport built it
    (``agent/turn_api_request.py``: ``_build_api_kwargs`` then the middleware), so a reserved-name
    alias (``hermes_tool_search`` on OpenAI/xAI Responses and xAI chat) is already on it; the
    capture records the transport's ``{alias: name}`` map beside the names.
    """

    if not isinstance(wire_receipt, Mapping):
        return []
    aliases = wire_receipt.get("bridge_aliases") or {}
    return [str(aliases.get(name, name)) for name in wire_receipt.get("names") or ()]


__all__ = [
    "AGENT_SURFACE_ATTR",
    "DispositionReason",
    "STATES",
    "ToolDisposition",
    "ToolSurface",
    "blocked_reason",
    "assemble_surface",
    "compute_tool_surface",
    "not_computed",
    "requested_tool_names",
    "unaliased_wire_names",
]
