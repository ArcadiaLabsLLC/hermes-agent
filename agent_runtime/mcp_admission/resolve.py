"""Resolution, pure — zero spawns (invariants 2-3): the config gate, the
requested and configured servers, the permission mode, the toolset scoping,
the operating skills and the requirement failures."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .outcomes import McpAdmission, McpAdmissionDenial
from .vocabulary import LANE_MISSION_CHAT, MCP_ADMISSION_DISABLED, MCP_OPERATING_SKILLS, MCP_READ_ONLY_SUBSET_UNKNOWN, MCP_SERVER_NOT_CONFIGURED, READ_ONLY_EXCLUDED_TOOLS, READ_ONLY_INCLUDED_TOOLS, _DEFAULT_CONNECT_TIMEOUT_SECONDS, _DEFAULT_MAX_TOOL_CALLS_PER_RUN, _MCP_TOOLSET_PREFIX, logger

__layer__ = "stores"


def admission_config(cfg: Any | None = None):
    """The ``agent_runtime.mcp_admission`` block from the ROOT runtime config.

    Harness-wide operator policy, so it loads through
    ``config.load_root_runtime_config`` — a sticky-active profile's own
    ``config.yaml`` must not be able to grant itself MCP admission.
    """

    from ..runtime_config import McpAdmissionConfig

    if cfg is not None:
        resolved = getattr(cfg, "mcp_admission", None)
        return resolved if resolved is not None else McpAdmissionConfig()
    try:
        from ..config import load_root_runtime_config

        return load_root_runtime_config().mcp_admission
    except Exception:  # pragma: no cover - defensive; a config fault must not open the gate
        logger.debug("MCP admission config load failed; treating admission as disabled", exc_info=True)
        return McpAdmissionConfig()


def admission_enabled(cfg: Any | None = None) -> bool:
    """The single kill switch: ``agent_runtime.mcp_admission.enabled``."""

    return bool(getattr(admission_config(cfg), "enabled", False))


def resolve_mcp_admission(
    persona,
    *,
    lane: str = LANE_MISSION_CHAT,
    permission_mode: str = "profile_default",
    cfg: Any = None,
) -> McpAdmission:
    """Resolve which declared MCP servers this persona run may register.

    Pure: reads config and the persona's profile declaration, and returns the
    compiled registration inputs. It performs **zero spawns** — a patched
    ``register_mcp_servers`` that fails the test if called is part of the suite.

    S66 removed the ``task`` / ``stage`` parameters. They rode the whole chain
    (here → ``_requested_servers`` → ``_effective_required_mcp_servers``) and
    were ignored at the bottom of it; no production caller passed either. They
    were residue of the retired role/work-description policy, and an accepted-
    and-discarded argument is exactly the silent no-op this campaign keeps
    finding.
    """

    from ..personas import role_from_persona

    config = admission_config(cfg)
    lane = str(lane or "").strip()
    permission_mode = str(permission_mode or "profile_default").strip() or "profile_default"
    # ``coerce_agent_role`` returns a plain ``str`` for anything outside the
    # one-member ``AgentRole`` enum, whose only member (``pm``) is mothballed,
    # so ``.value`` was the branch that could not be taken and the ``except``
    # labelled "defensive" was the live path. ``str()`` covers both: a StrEnum
    # stringifies to its own value.
    role = str(role_from_persona(persona))
    requested = tuple(_requested_servers(persona))
    timeout = _positive_float(getattr(config, "connect_timeout_seconds", None)) or _DEFAULT_CONNECT_TIMEOUT_SECONDS
    # No "unlimited" spelling: a missing / zero / negative / unparseable value
    # falls back to the default rather than retiring the bound. The root parser
    # already clamps, so this is the second half of the same rule for callers
    # that hand in a hand-built config object (tests, --explain-mcp previews).
    call_budget = _positive_int(getattr(config, "max_tool_calls_per_run", None)) or _DEFAULT_MAX_TOOL_CALLS_PER_RUN

    def _empty(denials: Sequence[McpAdmissionDenial]) -> McpAdmission:
        return McpAdmission(
            lane=lane,
            role=role,
            permission_mode=permission_mode,
            enabled=bool(getattr(config, "enabled", False)),
            requested=requested,
            denied=tuple(denials),
            connect_timeout_seconds=timeout,
            max_tool_calls_per_run=call_budget,
        )

    if not getattr(config, "enabled", False):
        return _empty(
            [
                McpAdmissionDenial(
                    server=name,
                    code=MCP_ADMISSION_DISABLED,
                    summary=(
                        f"MCP admission is disabled, so '{name}' is not registered for this run."
                    ),
                    fix_hint=(
                        "Set agent_runtime.mcp_admission.enabled: true in the ROOT "
                        "config.yaml to admit servers declared by this persona profile."
                    ),
                )
                for name in requested
            ]
        )

    if not requested:
        return _empty([])

    denials: list[McpAdmissionDenial] = []
    candidates = list(requested)

    configured = _configured_servers_for(persona)
    resolvable: dict[str, Any] = {}
    for name in candidates:
        raw = configured.get(name)
        if not isinstance(raw, Mapping):
            denials.append(
                McpAdmissionDenial(
                    server=name,
                    code=MCP_SERVER_NOT_CONFIGURED,
                    # S66: this text used to read "was requested by role
                    # '{role}'". That is WIRE TEXT an operator and the agent
                    # both read on a denied turn, and it named the wrong
                    # authority: nothing requests by role since S64: the request
                    # is `required_mcp_servers` ∪ the profile's own
                    # `mcp_servers` block. Being told a role denied you when a
                    # declaration did sends the fix to the wrong file.
                    summary=(
                        f"'{name}' is declared by this persona/profile, but the profile "
                        "declares no mcp_servers entry to spawn."
                    ),
                    fix_hint=(
                        f"Add an mcp_servers.{name} block to the persona profile's config.yaml "
                        "(portable form: agent_runtime/docs/machine_roots_path_portability.md)."
                    ),
                )
            )
            continue
        resolvable[name] = raw

    resolved: dict[str, Any] = {}
    if resolvable:
        from ..machine_roots import resolve_mcp_servers

        issues: list[tuple[str, Any]] = []
        resolved = resolve_mcp_servers(
            resolvable, on_issue=lambda name, issue: issues.append((name, issue))
        )
        for name, issue in issues:
            # Reuse the EXISTING machine_roots taxonomy verbatim (unbound_root,
            # root_target_missing, platform_unsupported, …) rather than minting a
            # parallel one — proving reuse is part of the R1 test plan.
            denials.append(
                McpAdmissionDenial(
                    server=str(name),
                    code=issue.code,
                    summary=issue.summary,
                    fix_hint=issue.fix_hint,
                )
            )

    admitted: list[str] = []
    compiled: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    for name in candidates:
        entry = resolved.get(name)
        if not isinstance(entry, Mapping):
            continue
        filtered, excluded, denial = _apply_permission_mode(
            name, dict(entry), permission_mode=permission_mode
        )
        if denial is not None:
            denials.append(denial)
            continue
        filtered["connect_timeout"] = _bounded_connect_timeout(filtered.get("connect_timeout"), timeout)
        admitted.append(name)
        compiled[name] = filtered
        blocked.extend(_prefixed_tool_names(name, excluded))

    return McpAdmission(
        lane=lane,
        role=role,
        permission_mode=permission_mode,
        enabled=True,
        requested=requested,
        server_names=tuple(admitted),
        denied=tuple(denials),
        server_configs=compiled,
        blocked_tool_names=tuple(sorted(set(blocked))),
        connect_timeout_seconds=timeout,
        max_tool_calls_per_run=call_budget,
    )


def _requested_servers(persona) -> list[str]:
    """What the persona DECLARES — required ∪ profile-configured.

    Reuses the two existing declaration surfaces rather than writing a third:
    ``profile_readiness.declared_mcp_server_names`` (required ∪ the profile's
    ``mcp_servers`` block, and deliberately NOT the ambient operator config for
    an unbound persona) unioned with ``_effective_required_mcp_servers``.

    S64 retired the role policy this docstring used to advertise (``role ==
    "qa"`` + visual proof ⇒ ``launcher_qa``). There is no role lane left here:
    an MCP dependency exists ONLY where the persona/profile declares it, which
    is why S66 also removed the ``task`` / ``stage`` parameters that fed it —
    they were inert, and no production caller ever passed either.
    """

    from ..profile_readiness import _effective_required_mcp_servers, declared_mcp_server_names

    names: list[str] = []
    for source in (
        declared_mcp_server_names(persona),
        _effective_required_mcp_servers(persona),
    ):
        for value in source or []:
            text = str(value or "").strip()
            if text and text not in names:
                names.append(text)
    return sorted(names)


def _configured_servers_for(persona) -> dict[str, Any]:
    """The persona profile's own ``mcp_servers`` map (never the ambient one)."""

    from ..parse_cache import cached_yaml_file
    from ..profile_context import resolve_persona_profile
    from ..profile_readiness import _configured_mcp_servers

    try:
        binding = resolve_persona_profile(persona)
        if binding.profile_home is None:
            return {}
        raw = cached_yaml_file(binding.profile_home / "config.yaml", default={}) or {}
        return dict(_configured_mcp_servers(raw))
    except Exception:  # pragma: no cover - defensive; a config fault must not open the gate
        logger.debug("MCP admission could not read the persona profile config", exc_info=True)
        return {}


def _apply_permission_mode(
    server: str, config: dict[str, Any], *, permission_mode: str
) -> tuple[dict[str, Any], tuple[str, ...], McpAdmissionDenial | None]:
    """Compose the permission mode onto the EXISTING per-server tool filter.

    ``read_only`` compiles the reviewer-shaped **positive** allowlist into
    ``mcp_servers.<name>.tools.include`` — the filter ``tools/mcp_tool.py``
    already implements (include wins over exclude) — so a denied tool is never
    registered, rather than registered and then blocked. No new filtering code
    path, per the design's §A step 4.

    Returns ``(config, blocked_raw_tool_names, denial)``. The blocked names are
    the reviewer row's ``denied`` set, threaded into ``blocked_tool_names`` as
    the resident-actor backstop; the *registration* boundary is the include list.
    """

    from ..tool_permissions import PERMISSION_MODE_READ_ONLY

    if permission_mode != PERMISSION_MODE_READ_ONLY:
        return config, (), None

    included = READ_ONLY_INCLUDED_TOOLS.get(server)
    if included is None:
        return (
            config,
            (),
            McpAdmissionDenial(
                server=server,
                code=MCP_READ_ONLY_SUBSET_UNKNOWN,
                summary=(
                    f"read_only admission has no reviewer-shaped subset for '{server}', "
                    "so nothing is admitted rather than admitting a surface it cannot subtract."
                ),
                fix_hint=(
                    f"Add '{server}' to agent_runtime.mcp_admission.READ_ONLY_INCLUDED_TOOLS "
                    "with a written security note, or run this persona in profile_default."
                ),
            ),
        )

    tools_filter = dict(config.get("tools") or {})
    authored = _name_list(tools_filter.get("include"))
    if authored:
        # A profile-authored include list is already narrower than the server's
        # full surface; read_only can only narrow it further, never resurrect a
        # tool the reviewer row does not allow.
        allowed = [name for name in authored if name in set(included)]
    else:
        allowed = list(included)
    tools_filter["include"] = allowed
    # An explicit include wins over exclude upstream, so the exclude entry is
    # redundant for registration. It is still written so an operator reading the
    # compiled config sees BOTH halves of the decision, and so a future upstream
    # that honours both stays correct.
    tools_filter["exclude"] = sorted(
        set(_name_list(tools_filter.get("exclude"))) | set(READ_ONLY_EXCLUDED_TOOLS.get(server, ()))
    )
    config["tools"] = tools_filter
    return config, tuple(READ_ONLY_EXCLUDED_TOOLS.get(server, ())), None


def _name_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value]
    return []


def _prefixed_tool_names(server: str, tool_names: Iterable[str]) -> list[str]:
    """Registry/wire names for raw MCP tool names, via the upstream builder.

    Imported lazily and only on an admitted read_only run: importing
    ``tools.mcp_tool`` pulls the whole MCP SDK (~200ms), which no preview or
    disabled-flag path should ever pay. Mirroring the ``mcp__<server>__<tool>``
    convention locally was rejected — a silently drifting mirror is exactly the
    class of bug ``mcp_lane`` needed a guard test for.
    """

    names = [str(name).strip() for name in tool_names or [] if str(name or "").strip()]
    if not names:
        return []
    try:
        from tools.mcp_tool_schema import mcp_prefixed_tool_name
    except Exception:  # pragma: no cover - MCP SDK absent; the tools.exclude filter still applies
        logger.debug("MCP admission could not resolve prefixed tool names", exc_info=True)
        return []
    return [mcp_prefixed_tool_name(server, name) for name in names]


def _bounded_connect_timeout(configured: Any, budget: float) -> float:
    """Never let a server's own connect timeout outrun the admission budget.

    ``launcher_qa`` declares ``connect_timeout: 60``; a mission-chat turn cannot
    spend that on a capability probe. Clamping here means the spawn attempt
    self-terminates inside the budget instead of leaving a thread wedged behind
    the caller's deadline.
    """

    value = _positive_float(configured)
    if value is None:
        return budget
    return min(value, budget)


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def scope_toolsets_to_admission(
    toolsets: Iterable[str] | None, *, admitted_servers: Iterable[str] | None
) -> list[str]:
    """Keep only the MCP toolsets THIS run was admitted; add the admitted ones.

    Applied after permission-mode resolution, which is what makes the
    ``unbounded`` rule hold by construction. It was load-bearing while
    ``unbounded`` resolved ``all_registered_toolsets()`` — in a warm
    multi-persona process that set contains another persona's admitted ``mcp-*``
    toolsets. Since S0a A1 both modes resolve the persona's own declaration, so
    this is defensive; it stays because "no permission mode can widen the
    admitted set" must not depend on what today's profiles happen to declare.

    Non-MCP toolsets pass through untouched and in order.
    """

    admitted = [str(name).strip() for name in admitted_servers or [] if str(name or "").strip()]
    keep = {f"{_MCP_TOOLSET_PREFIX}{name}" for name in admitted} | set(admitted)
    # ONE registry read per call, not one per toolset name. On every lane that
    # registers no MCP at all — which is every lane until an operator flips the
    # flag — the alias map is empty and the prefix test is the whole check.
    aliases = _mcp_toolset_aliases()
    scoped = [
        name
        for name in (toolsets or [])
        if not _is_mcp_toolset(name, aliases) or str(name) in keep
    ]
    for name in admitted:
        toolset = f"{_MCP_TOOLSET_PREFIX}{name}"
        if toolset not in scoped:
            scoped.append(toolset)
    return scoped


def _mcp_toolset_aliases() -> frozenset[str]:
    """Alias names that point at an ``mcp-*`` toolset in this process."""

    try:
        from tools.registry import registry

        aliases = registry.get_registered_toolset_aliases()
    except Exception:  # pragma: no cover - registry is always importable in-process
        return frozenset()
    return frozenset(
        str(alias)
        for alias, target in (aliases or {}).items()
        if str(target).startswith(_MCP_TOOLSET_PREFIX)
    )


def _is_mcp_toolset(name: Any, aliases: frozenset[str]) -> bool:
    """Is this toolset name an MCP toolset — canonical ``mcp-x`` or an alias?

    The registry registers ``mcp-<server>`` and an alias ``<server>`` pointing at
    it, so a bare server name in ``enabled_toolsets`` resolves to the same tools.
    Both spellings have to be scoped or the strip leaks through the alias.
    """

    text = str(name or "").strip()
    if not text:
        return False
    return text.startswith(_MCP_TOOLSET_PREFIX) or text in aliases


def admitted_operating_skill_ids(
    admission: McpAdmission | None, *, granted_skills: Iterable[str] | None
) -> list[str]:
    """The operating manual(s) THIS run must have in context, in grant order.

    Two gates, both required, and each one narrows:

    1. **Admitted.** ``admission.server_names`` is what actually survived the
       profile-declared admission path — flag, declaration, machine
       resolvability, and permission mode. Nothing else is consulted, so a
       persona that merely DECLARES a server (and will get a typed denial line
       instead of tools) never pays for its manual.
    2. **Granted.** The skill must already be on the persona's own skill list.
       This function turns an existing grant into an active load; it never
       invents one. An operator who revokes the grant has revoked the preload,
       with no second place to look.

    Order follows the persona's grant list rather than the server list, so the
    preload set follows the profile grant order. Pure: no registry read, no
    filesystem, no resolve.
    """

    if admission is None or admission.is_empty:
        return []
    wanted: set[str] = set()
    for server in admission.server_names:
        wanted.update(MCP_OPERATING_SKILLS.get(str(server), ()))
    if not wanted:
        return []
    resolved: list[str] = []
    for skill in granted_skills or ():
        name = str(skill or "").strip()
        if name in wanted and name not in resolved:
            resolved.append(name)
    return resolved


def admission_requirement_failures(
    admission: McpAdmission | None,
    *,
    declared_servers: Iterable[str],
    lane: str | None = None,
    registered_servers: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Typed ``requirement_failures`` for a persona, admission-aware.

    One row per declared server, at most, resolved by precedence:

    1. Admitted (and not denied) ⇒ **no row** (R-S0a-4, 2026-09-03). It used to
       be "admitted AND registered in THIS process", which made the STEADY state
       report as a failure: the CLI preview process registers no MCP at all, and
       inside the serve ``teardown_mcp_admission`` removes the run's registry
       scope at the end of every admitted run, so "admitted, not currently
       registered" is what admission normally looks like from outside a run. All
       three mission personas reported 1-3 ``mcp_not_registered_on_lane`` rows
       for servers they were, in fact, admitted. Per-run registration is
       receipted where it happens (``mcp_admitted_servers`` /
       ``mcp_admission_transport`` on the turn record); the preview reports the
       admitted names under ``admitted_mcp_servers``. Cross-persona silencing is
       impossible because ``admission.server_names`` is already per-persona.
    2. Admission produced a typed denial ⇒ that denial's row, which is strictly
       more actionable than the generic lane row.
    3. Otherwise ⇒ the existing R0 ``mcp_not_registered_on_lane`` row.

    With admission disabled (``admission is None`` or ``enabled=False``) this is
    byte-identical to calling ``mcp_lane_requirement_failures`` directly — the
    flag-off path must not change what R0 reports.
    """

    from ..mcp_lane import mcp_lane_requirement_failures, registered_mcp_server_names

    declared = [str(name).strip() for name in declared_servers or [] if str(name or "").strip()]
    if admission is None or not admission.enabled:
        return mcp_lane_requirement_failures(
            declared_servers=declared, lane=lane, registered_servers=registered_servers
        )

    registered = (
        registered_mcp_server_names()
        if registered_servers is None
        else frozenset(str(name).strip() for name in registered_servers or [])
    )
    # Admitted for THIS persona. NOT intersected with what is registered right
    # now: registration is per-run and torn down after it, so the intersection
    # answered "is a run in flight in this process" rather than "was this persona
    # admitted" (R-S0a-4). ``registered`` is still threaded to the lane rows
    # below, where an UNADMITTED declaration is judged against what the process
    # actually holds.
    effective = frozenset(admission.server_names)
    denials = {denial.server: denial for denial in admission.denied}

    rows: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for name in declared:
        if name in effective:
            continue
        denial = denials.get(name)
        if denial is not None and denial.code != MCP_ADMISSION_DISABLED:
            rows.append(denial.row())
            continue
        unresolved.append(name)
    rows.extend(
        mcp_lane_requirement_failures(
            declared_servers=unresolved, lane=lane, registered_servers=registered | effective
        )
    )
    return rows
