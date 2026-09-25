"""``_build_snapshot_in_runtime_scope`` — assembling the frame's sections.
"""

from __future__ import annotations

import time

from hermes_time import now
from agent_runtime.board_store import BoardStore
from agent_runtime.office_store import OfficeStore
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.decision_contract_registry import (
    CONTRACT_SCHEMA_VERSION,
    contract_hash,
)
from agent_runtime.events import CachedEventLog
from agent_runtime.migrations import effective_config_summary, migration_status
from agent_runtime.operator_channels import operator_channel_summary
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    active_persona_instance_agent_summaries,
    persona_instance_summary,
)
from agent_runtime.persona_chat_history import (
    DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
    persona_chat_history_summary,
    persona_chat_trace_summary,
)
from agent_runtime.persona_instance_identity import identity_aliases_for_rows
from agent_runtime.persona_lifecycle import is_runtime_persona
from agent_runtime.parity import ProjectionAccountant, events_position
from agent_runtime.prompt_observability import (
    _SkillObservabilityResolver,
    snapshot_prompt_observability,
)
from agent_runtime.running_work import build_running_work
from agent_runtime.store import AgentStore, RealmStore, WorkspaceStore

from agent_runtime.snapshot.context import SnapshotSummary, _SNAPSHOT_BUILD_CONTEXT
from agent_runtime.snapshot.receipts import (
    _keyed,
    _persona_chat_history_frame,
    _runtime_paths_diagnostic,
)
from agent_runtime.snapshot.build_log import _log_agents_readiness_split, _timed_section
from agent_runtime.snapshot.envelope import _parity_envelope
from agent_runtime.snapshot.boards import _boards_summary
from agent_runtime.snapshot.offices import _offices_summary
from agent_runtime.snapshot.summaries import (
    _agent_summary,
    _available_persona_summary,
    _realm_summary,
    _repo_scopes_summary,
    _safe_model_label,
    _workspace_summary,
)

__all__ = [
    "_build_snapshot_in_runtime_scope",
]


def _build_snapshot_in_runtime_scope(
    agent_store=None,
    event_log=None,
    prompt_skills_catalogs=None,
    *,
    session_db,
) -> dict:
    _build_started = time.perf_counter()
    # THE SOURCE POSITION IS CAPTURED HERE, BEFORE THE FIRST SECTION IS READ —
    # not in ``_parity_envelope`` at the end of the build. Every section below
    # is read after this stat, so the offset is a LOWER bound on what the core
    # carries: anything appended during the build is newer than the offset and
    # replays to the client as a delta. The end-of-build reading this replaces
    # made the opposite, unrecoverable claim — see ``parity.events_watermark``'s
    # "which instant the offset describes" block for the measured 2026-08-21
    # failure (an agent dropped mid-build vanished from every connected client).
    _build_start_position = events_position()
    _sections_ms: dict[str, int] = {}
    agent_store = agent_store or AgentStore()
    # A snapshot calls for_task/for_session/tail dozens of times on the same log;
    # CachedEventLog reads events.jsonl once and serves all of them from memory.
    event_log = event_log or CachedEventLog()
    # Force + time the one-shot CachedEventLog materialization here (the ~1s
    # event-log read, measured 2026-07-23) before other consumers warm it, so
    # ``sections_ms.events`` honestly attributes that cost. ``recent_events`` is
    # a pure read reused later by the parity envelope (watermark + event-summary
    # warnings); the observability consumer it also named went with S9.
    with _timed_section(_sections_ms, "events"):
        recent_events = event_log.tail(20)
    # S56 removed the LAST of these seeds. ``workers = []`` was kept by S47 as
    # "the one surviving seed still passed into a live projection"
    # (``derive_from_workers``) — but an always-empty list can only make a
    # projection emit a constant, which is exactly why ``tasks`` and
    # ``workspaces[].goals`` went at S47 (ledger item 5). The projection is now
    # ``PersonaInstanceStore.ensure_for_personas(personas)`` and takes no worker
    # argument; the worker session store it read is deleted. The eight earlier
    # look-alikes (``runs``, ``incidents``, ``proofs``,
    # ``role_envelopes``, ``role_checklists``, ``repo_bundles``,
    # ``runtime_instances``) fed the mission projections S9/S18/S27 removed and
    # were assigned-never-read; so were ``execution_mode`` (the retired Mission
    # Daemon's mode string) and ``live_channel_task_ids``.
    cfg = load_agent_runtime_config()
    # Base-profile foundation: Mission Control shows the seeded store (base only). On a
    # cold store, fall back to the base seed itself — NOT ensure_persisted_personas, which
    # also returns the dormant typed catalog for resolution and would surface mothballed
    # pipeline personas that are not meant to be shown.
    agents = [agent for agent in agent_store.list_all() if is_runtime_persona(agent)]
    workspace_store = WorkspaceStore()
    realm_store = RealmStore()
    workspaces = workspace_store.list_all(include_archived=True)
    realms = realm_store.list_all(include_archived=True)
    # Active scope names for the runtime situational HUD (the same realm/ws the
    # launcher scope line renders); resolved once and fed to every lane's HUD.
    active_workspace_name = next(
        (getattr(w, "name", None) for w in workspaces if getattr(w, "id", None) == workspace_store.active_id()),
        None,
    )
    active_realm_name = next(
        (getattr(r, "name", None) for r in realms if getattr(r, "id", None) == realm_store.active_id()),
        None,
    )
    build_context = _SNAPSHOT_BUILD_CONTEXT.get()
    skill_resolver = _SkillObservabilityResolver(
        root_registries=(
            build_context.skill_root_registries if build_context is not None else None
        )
    )
    # ``agents_readiness`` times TWO different walks and always has. Its name
    # says readiness, so a remedy plan reading the section off a build log
    # convicts ``profile_readiness_for_persona`` — and on this section that is
    # the SMALLER half. Measured against the operator's own profiles root
    # (5 runtime personas, 2026-08-22): first build in a process 4,001 ms, of
    # which the summary/tool-visibility half is 3,054 ms and the readiness walk
    # 947 ms; steady state in the same process 183 ms, split 36 / 146. The two
    # halves also move for unrelated reasons — the visibility half is the
    # registry populate and the ``check_fn`` sweep, the walk is profile config
    # plus skill resolution — so one number over both cannot attribute either.
    #
    # The split is a LOG RECEIPT, not two new ``sections_ms`` keys, and the
    # reason is a contract boundary rather than taste. ``sections_ms`` rides the
    # parity envelope, which rides the hydrate frame, which is byte-pinned by the
    # committed stream goldens AND by the Launcher's mirror of them
    # (``test/fixtures/harness_stream/``) — "stream goldens change only in a
    # cross-stack landing", as their own gate puts it. Two extra keys there would
    # have been a cross-stack fixture landing for an observability nicety, and a
    # hermes-only half of one is precisely the failure this repo already paid for
    # once: hermes green, the Launcher's producer-contract byte-compare red on
    # every push. The number an operator actually reads is ``sections_top`` on
    # the ``snapshot_build_core`` line in ``agent.log`` — a log line, not a frame
    # — so the attribution belongs there, where it costs no contract at all.
    #
    # ``agents_readiness`` therefore keeps its exact span, meaning and key.
    _readiness_split: dict[str, int] = {}
    with _timed_section(_sections_ms, "agents_readiness"):
        from ..profile_readiness import profile_readiness_for_persona

        with _timed_section(_readiness_split, "walk_ms"):
            readiness_by_persona_id = {
                str(getattr(agent, "id", "") or ""): profile_readiness_for_persona(
                    agent, skill_resolver=skill_resolver
                )
                for agent in agents
            }
        with _timed_section(_readiness_split, "tool_visibility_ms"):
            agent_summaries = [
                _agent_summary(
                    agent,
                    include_tool_details=True,
                    readiness=readiness_by_persona_id.get(
                        str(getattr(agent, "id", "") or "")
                    ),
                )
                for agent in agents
            ]
    _log_agents_readiness_split(_readiness_split)
    available_personas = _available_persona_summary(agents)
    personas_by_id = {str(getattr(agent, "id", "") or ""): agent for agent in agents}
    # S56: the persona-instance roster is UNCONDITIONAL. It was gated on
    # ``enterprise_worker_sessions.enabled AND .persona_instance_runtime`` — a
    # misnomer inherited from the worker lane — and the assignment list on a
    # second field of the same block. The roster IS the identity substrate every
    # Mission Control surface keys on, the enabled shape has been the only shape
    # for months, and no code in either repo branches on a disabled verdict. Both
    # gates went with the config block.
    instance_store = PersonaInstanceStore(event_log=event_log)
    persona_instances = instance_store.ensure_for_personas(agents)
    topology_persona_instances = persona_instances
    agent_summaries = [
        *agent_summaries,
        *active_persona_instance_agent_summaries(
            persona_instances, personas_by_id, readiness_by_persona_id
        ),
    ]
    migration = migration_status()
    # Hoisted out of the ``data`` literal so their cost is attributable in
    # ``sections_ms`` (both were profiled hot: prompt_observability ~5s, the
    # skills-catalog walks inside it; boards/offices are local-only reads).
    with _timed_section(_sections_ms, "prompt_observability"):
        prompt_observability_section = snapshot_prompt_observability(
            personas=agents,
            persona_instances=persona_instances,
            session_db=session_db,
            daemon=None,
            realm=active_realm_name,
            workspace=active_workspace_name,
            active_workspace_id=workspace_store.active_id(),
            catalog_sink=prompt_skills_catalogs,
            skill_resolver=skill_resolver,
        )
    with _timed_section(_sections_ms, "boards_offices"):
        boards_projection = _boards_summary(BoardStore(event_log=event_log), workspaces)
        boards_section = _keyed(boards_projection.boards, "board_id")
        offices_projection = _offices_summary(OfficeStore(event_log=event_log), workspaces, realms)
        offices_section = _keyed(offices_projection.offices, "workspace_id")
    running_work_accountant = ProjectionAccountant("running_work")
    with _timed_section(_sections_ms, "running_work"):
        running_work_section = build_running_work(running_work_accountant)
    data = {
        "schema_version": 2,
        # Legacy wire names retained for Launcher/core-fixture compatibility;
        # the hash is now computed from the event-only registry.
        "decision_contract_version": CONTRACT_SCHEMA_VERSION,
        "decision_contract_hash": contract_hash(),
        "event_contract_version": CONTRACT_SCHEMA_VERSION,
        "generated_at": now(),
        "summary": SnapshotSummary(persona_instances=len(topology_persona_instances)).as_dict(),
        # Single runtime-default authority, resolved + provenance-stamped, as a
        # typed top-level block so surfaces (launcher model-switcher caption,
        # `hermes harness config show`) report what agents actually follow
        # without re-deriving the top-level-vs-agent_runtime precedence.
        "runtime_default": {
            "model": _safe_model_label(cfg.default_model),
            "provider": _safe_model_label(cfg.default_provider),
            "api_mode": cfg.default_api_mode,
            "model_source": getattr(cfg, "default_model_source", "unset"),
            "provider_source": getattr(cfg, "default_provider_source", "unset"),
        },
        "runtime_config": effective_config_summary(cfg),
        "migration": migration,
        "prompt_observability": prompt_observability_section,
        "repo_scopes": _repo_scopes_summary(),
        "workspaces": [
            _workspace_summary(
                item,
                persona_instances=topology_persona_instances,
                active_id=workspace_store.active_id(),
            )
            for item in workspaces
        ],
        "realms": [
            _realm_summary(item, workspaces=workspaces, active_id=realm_store.active_id())
            for item in realms
        ],
        # Mission Board projection: board defs + bounded, redaction-safe card
        # rows, scoped by workspace. Local reads only — NO git/sync calls in the
        # snapshot path (conflict state comes from local sidecar files, never a
        # git call). Cards carry planning state only.
        "boards": boards_section,
        # Whole boards the build could not read: ``board.json`` exists and does
        # not decode, so no row above could be built for it. Sibling to each
        # row's ``cards_unreadable`` (rows the platform took INSIDE a board) and
        # twin of ``offices_unreadable``. Additive, and never silently zero.
        "boards_unreadable": boards_projection.unreadable,
        # Mission Office projection: surface defs + bounded actor rows, keyed by
        # workspace. Local reads only — conflict state comes from local sidecar
        # files and the `unpublished` honesty flag from the local baseline
        # sidecar; NEVER a git call in the snapshot path.
        "offices": offices_section,
        # How many workspaces have an office the build could not read AT ALL —
        # the surface file exists and would not decode, so no row above could be
        # built for it. Sibling in spirit to each row's ``actors_unreadable``:
        # that one counts rows the platform took INSIDE an office, this one
        # counts whole offices it took. Additive — an old launcher ignores it —
        # and never silently zero, which is the only reason the key exists.
        "offices_unreadable": offices_projection.unreadable,
        # Unified background-work projection: terminal processes, subagent
        # delegations, in-flight chat turns, MCP servers, cron jobs — one row
        # vocabulary across six subsystems, durable-first so a cold CLI lane
        # answers as honestly as the serve process that spawned the work. Every
        # lane carries its own ok/unavailable health under ``sources``; an
        # unreadable lane is REPORTED, never rendered as "nothing running".
        "running_work": running_work_section,
        "active_workspace_id": workspace_store.active_id(),
        "active_realm_id": realm_store.active_id(),
        "agents": agent_summaries,
        "available_personas": available_personas,
        "runtime_paths_diagnostic": _runtime_paths_diagnostic(available_personas),
    }
    data["persona_instance_runtime"] = {"enabled": True}
    # S4: persona_instances ships as an id-keyed map (the identity substrate
    # the whole roster keys on — the store is already keyed on disk). The
    # ROW LIST is built first because the identity_map alias resolver derives
    # from the ordered rows; the frame then keys it by ``persona_instance_id``.
    persona_instance_rows = [
        persona_instance_summary(
            instance,
            personas_by_id.get(str(getattr(instance, "persona_id", "") or "")),
            profile_readiness=readiness_by_persona_id.get(
                str(getattr(instance, "persona_id", "") or "")
            ),
        )
        for instance in persona_instances
    ]
    # Legacy persona-instance id -> canonical id aliases (durable
    # reconciler registry + structurally derivable drift still live in
    # this snapshot). Consumers key dedup on this instead of heuristics.
    data["identity_map"] = identity_aliases_for_rows(persona_instance_rows)
    data["persona_instances"] = _keyed(persona_instance_rows, "persona_instance_id")
    history_accountant = ProjectionAccountant("persona_chat_history")
    trace_accountant = ProjectionAccountant("persona_chat_trace")
    # Full history (with message tails) is computed once and used to build the
    # operator_channels conversations (their tail slimming is S4's concern).
    # The FRAME carries recency pointers only (S2) — the tail bytes leave, the
    # anchors stay.
    _persona_chat_started = time.perf_counter()
    omitted_history_session_ids: set[str] = set()
    persona_chat_history_full = persona_chat_history_summary(
        persona_instances=persona_instances,
        session_db=session_db,
        message_tail=DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
        accountant=history_accountant,
        omitted_session_ids=omitted_history_session_ids,
    )
    data["persona_chat_history"] = _persona_chat_history_frame(persona_chat_history_full)
    data["persona_chat_trace"] = persona_chat_trace_summary(
        persona_instances=persona_instances,
        event_log=event_log,
        message_tail=DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
        accountant=trace_accountant,
    )
    conversation_accountant = ProjectionAccountant("operator_conversation")
    live_operator_channels = operator_channel_summary(
        persona_instances=persona_instances,
        persona_chat_history=persona_chat_history_full,
        persona_chat_trace=data["persona_chat_trace"],
        accountant=conversation_accountant,
        intentionally_omitted_history_session_ids=omitted_history_session_ids,
    )
    _sections_ms["persona_chat"] = int(
        max(0.0, (time.perf_counter() - _persona_chat_started)) * 1000
    )
    # S4: operator_channels ships as an id-keyed map (channel_id). S18
    # removed the archived-task channels this used to be merged with, so the
    # live channels are the whole input; ``_keyed`` still keeps the first
    # occurrence on a duplicate id rather than silently overwriting.
    data["operator_channels"] = _keyed(live_operator_channels, "channel_id")
    # AX2 (2026-08-31): the ``persona_assignments`` block LEFT the frame, and
    # with it the only reason this builder opened the assignment store. S8 had
    # already evicted ``recent`` to a pointer and kept ``active`` for "the
    # launcher roster"; the launcher then deleted every read of the block
    # (``6bf48ba26``) and keeps a test asserting that a payload still carrying
    # it puts nothing on an instance. A projection whose sole consumer pins its
    # own indifference is not a contract, it is a cost — and the store read was
    # a directory walk on every build. ``harness persona assignments --json`` is
    # the surviving reader for residual rows.
    completeness = {
        "persona_chat_history": history_accountant.summary(),
        "persona_chat_trace": trace_accountant.summary(),
        "operator_conversation": conversation_accountant.summary(),
        "running_work": running_work_accountant.summary(),
    }
    drop_samples = (
        history_accountant.drop_samples()
        + trace_accountant.drop_samples()
        + conversation_accountant.drop_samples()
        + running_work_accountant.drop_samples()
    )
    # Guarantee the documented section keys exist even when a lane was skipped
    # (e.g. persona_chat when persona-instance runtime is disabled) so consumers
    # can rely on a stable shape.
    for _section_key in (
        "agents_readiness",
        "prompt_observability",
        "events",
        "persona_chat",
        "boards_offices",
        "running_work",
    ):
        _sections_ms.setdefault(_section_key, 0)
    _parity_started = time.perf_counter()
    data["parity"] = _parity_envelope(
        data,
        build_started=_build_started,
        build_start_position=_build_start_position,
        last_event=recent_events[-1] if recent_events else None,
        recent_events=recent_events,
        completeness=completeness,
        drop_samples=drop_samples,
        sections_ms=_sections_ms,
    )
    # ``_sections_ms`` is stored by reference in the envelope, so recording the
    # parity section's own duration after the call is reflected in the frame.
    _sections_ms["parity"] = int(max(0.0, (time.perf_counter() - _parity_started)) * 1000)
    return data
