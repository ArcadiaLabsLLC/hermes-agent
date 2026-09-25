"""The parity envelope: slimming, eviction markers, size, age and the
root/profile identity stamps.
"""

from __future__ import annotations

import json
import time
import hashlib
from datetime import datetime

from hermes_time import now
from agent_runtime import paths
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.parity import PARITY_ENVELOPE_VERSION, events_watermark
from agent_runtime.resolution import (
    resolution_payload,
    resolve_runtime,
    suspect_default_root,
)
from agent_runtime.serde import to_jsonable

from agent_runtime.snapshot.context import SNAPSHOT_CONTRACT_VERSION
from agent_runtime.snapshot.warnings import (
    _event_summary_warnings,
    _parity_warnings,
    _redaction_observed,
)
from agent_runtime.snapshot.summaries import _safe_model_label, _safe_repo_scope_label

__all__ = [
    "_parity_envelope",
    "_projection_age_ms",
    "_runtime_profile_identity",
    "_runtime_root_identity",
    "_snapshot_payload_size",
]


def _parity_envelope(data, *, build_started, last_event, completeness, drop_samples, recent_events=None, sections_ms=None, build_start_position=None):
    """The S0 observability envelope: provenance + completeness + parity warnings.

    Additive and self-describing — turns the snapshot's silent drops into reported
    data and dates the snapshot against the event log so a reader knows how far
    behind it is. See the snapshot-architecture brain note.
    """

    last_ts = getattr(last_event, "ts", None) if last_event is not None else None
    watermark = events_watermark(last_event_ts=last_ts, position=build_start_position)
    resolution = resolve_runtime()
    cfg = load_agent_runtime_config()
    warnings = _parity_warnings(data)
    warnings.extend(_event_summary_warnings(recent_events or []))
    if watermark.get("event_offset") is None:
        # The frame cannot date itself against the log. Riders must resync
        # rather than read the absent position as byte 0 (= "caught up").
        warnings.append(
            {
                "code": "event_offset_unknown",
                "detail": (
                    "the event log's end offset could not be read, so this frame carries no "
                    "source position; watermark-gated consumers must resync instead of resuming "
                    f"({watermark.get('event_offset_error') or 'unreadable'})"
                ),
            }
        )
    if suspect_default_root(resolution):
        warnings.append(
            {
                "code": "suspect_default_root",
                "detail": "runtime root resolved through the default layer, but no store marker directories (persona_instances/, sessions/, agents/) exist; check runtime-root pins",
            }
        )
    return {
        "envelope_version": PARITY_ENVELOPE_VERSION,
        # S8 (DEEP SLIM inside live rows): the same history-eviction knife one
        # level deeper. Goal rows become compact HEADS (heavy detail →
        # ``harness goal detail``); the ``skills_catalogs`` table leaves the frame
        # (rows keep ``*_ref`` hashes → ``harness skills catalog --hash``); the
        # ``runs`` map keeps only ACTIVE runs (history → ``harness run list``);
        # ``persona_assignments.recent`` and stale ``chat_contexts`` rows are
        # evicted to pointers; archived operator channels become pointer stubs
        # (transcript → ``harness task history``). Every eviction is accounted
        # (typed ``*_ref`` / ``detail_ref`` / ``evicted`` markers), never a silent
        # absence. S2/S3/S4 shape unchanged. Launcher pin
        # (kSupportedMissionContractVersion) moves in lockstep.
        #
        # 44 (snapshot residue-slim R1/R2/R5a, 2026-07-17; 43 was taken by the
        # office-realm-sync landing): the dead ``capabilities`` /
        # ``observability.capabilities`` / ``event_contracts`` / ``blueprints`` /
        # ``blueprint_runs`` frame sections (zero readers in all three repos) are
        # DELETED; ``persona_instances`` / ``agents`` rows evict the heavy
        # tool-detail payloads behind a typed ``visibility_ref`` (fetched via
        # ``harness persona-instance detail``) and ``agent_hud_state`` is RETIRED;
        # 45 removes mission rows while retaining chat/runtime graph projections.
        #
        # 46 (S47, 2026-08-01): two emitted fields whose values no code path
        # could move leave the frame — ``runtime_config.role_envelope`` (the
        # config block S44's store-family cut left governing nothing, shipping
        # ``enabled: true``) and ``workspaces[].goals`` (a count over an
        # always-empty seed). Field removals, not section removals, but the
        # S9/S10 rule is the same: anything that leaves the wire bumps, and the
        # Launcher pin moves in the same wave.
        # 47 (S56, 2026-08-01): one coherent wave, one bump. Leaving the frame:
        # every `worker_session` trace (the store is deleted — `status`'s
        # `worker_sessions` + `active_worker_sessions` rows, the
        # `observability` worker signals/rows, `dirty_state`'s four worker
        # counters, `persona_instances[].active_worker_session_id`); the
        # constant-by-construction repo-bundle wires `repo_bundles` /
        # `repo_bundle_closeout` / `bundle_queue` / `repo_locks` and the
        # duplicate `lanes` (doc 19 filed the last two as asserted-constant
        # debt); `production_envelope` (hand-written prose, several claims false
        # against this tree) with `swarm` / `swarm_budget`; and SEVEN
        # `runtime_config` blocks that no production code read —
        # `continuous_role_sessions`, `enterprise_worker_sessions`,
        # `normal_worker_flow`, `repo_bundle_routing`,
        # `simplified_agent_contract`, `swarm`, plus three of the four
        # `supervision` fields. The persona-instance roster stops being gated on
        # `enterprise_worker_sessions.persona_instance_runtime` and ships
        # unconditionally. The Launcher pin moves in the same wave.
        #
        # 48 (S57, 2026-08-01): the S56 reader-gate's `UNRULED_DEBT` bucket is
        # emptied and the last whole store of the repo-bundle lane goes. Leaving
        # the frame: TWENTY-NINE `runtime_config` scalars with no production
        # reader (the `daemon_*` family, the four `live_run_*` budgets, the four
        # `liveness_*` knobs, the three `artifact_storage_*` watermarks, the two
        # mission ceilings, the two neko caps, `heartbeat_ttl_seconds`,
        # `max_actions_per_tick`, `root_node_mode`,
        # `preferred_goal_execution_mode`, `scope_wait_deadline_seconds`,
        # `run_lease_seconds`, `tool_wait_timeout_seconds`,
        # `child_progress_min_interval_seconds`, `deploy_timeout_seconds`) —
        # all VERIFIED present on the live frame at contract 47, so this edits
        # the wire rather than only the code — together with the validator arms
        # that range-checked them, and `migration.counts.repo_bundles`, the last
        # wire trace of the `RepoBundleStore` deleted whole in the same wave. The
        # Launcher pin moves in the same wave.
        #
        # 49 (S58, 2026-08-01): ``runtime_config.migration`` was a byte-for-byte
        # duplicate of the authoritative top-level ``migration`` block. The
        # Launcher reads neither copy; its supported-contract pin moves in
        # lockstep with this emitted-field removal.
        # 51 retires the last task/proof migration-count rows and the
        # run-summary conversation source. The legacy contract-hash wire names
        # remain compatibility aliases for the event-only registry.
        #
        # 52 (WP-H1, 2026-08-03) ADDS the ``running_work`` section — the first
        # additive move in several waves, and the reason the pin still has to
        # travel: the Launcher's ``MissionSnapshotEnvelope.health()`` requires
        # EXACT equality, so an additive section that arrives under an unbumped
        # version would be invisible rather than merely unread. The section
        # carries its own ``sources`` health block and a ``completeness``
        # accountant row of the same name. The Launcher pin
        # (``kSupportedMissionContractVersion``) moves to 52 in WP-L1, and the
        # live venv is refreshed only AFTER that lands — refreshing first
        # fail-closes the console with a ``newerContract`` banner.
        #
        # 52 KEPT (WP-H2, 2026-08-03) — ``running_work`` gained its sixth lane,
        # ``dispatch``, and this entry records WHY that did not bump. The rule
        # this ledger actually states is not "any wire change bumps"; it is
        # (a) anything that LEAVES the wire bumps (the S9/S10 rule, cited at 46),
        # and (b) an ADDITION bumps when it would otherwise be "invisible rather
        # than merely unread" — the 52 entry above, where the Launcher had no
        # parse for the new section at all. Neither applies here: nothing left
        # the wire, and 52 itself published ``dispatch`` inside
        # ``RUNNING_WORK_KINDS`` with the stated intent that "the wire
        # vocabulary is complete from the first landing and a consumer does not
        # have to re-derive it when the lane arrives". What arrives is a sixth
        # key in a health MAP plus rows carrying a ``kind`` string the version
        # already declared, both of which a consumer pinned at 52 consumes. The
        # Launcher pin has also not moved to 52 yet (WP-L1 is pending), so the
        # section and its sixth lane reach the Launcher in the SAME wave either
        # way. The constraint this puts on WP-L1 is explicit and load-bearing:
        # parse ``sources`` as a map and ``kind`` as an open string. An
        # exhaustive five-lane enum switch would turn this ruling into a
        # fail-closed frame and would have needed the bump instead.
        #
        # 52 KEPT AGAIN (WP-L2 attribution, 2026-08-03) — the operator
        # conversation gained a ``harness_delivery`` message ``kind`` and a
        # typed ``delivery`` sub-block ({dispatch_id, notify_operator}) on the
        # row a dispatch DELIVERY turn produces. The same two-part rule answers
        # it: (a) nothing LEFT the wire — the row still projects role="operator"
        # with the same id/text/timestamps, so a consumer that ignores the kind
        # renders exactly what it renders today; and (b) it is not "invisible
        # rather than merely unread" — the Launcher's conversation adapter falls
        # through unknown kinds to a generic bubble BY DESIGN, and it parses
        # this one in the SAME wave (WP-L2 lands both halves). The 52 entry
        # above bumped because the Launcher had no parse for a whole new
        # SECTION; here the section, the message list and the row are all
        # pre-existing and already parsed. The constraint this puts on the
        # consumer is the same one the dispatch lane put there: conversation
        # ``kind`` stays an OPEN string. An exhaustive switch over it would turn
        # this ruling into a fail-closed frame and would have needed the bump.
        #
        # 52 KEPT, THIRD TIME (WP-L2 review fixes, 2026-08-03) — the
        # ``delivery`` sub-block gained ``state`` (the settled dispatch outcome)
        # and the ``running_work`` dispatch lane gained terminal ``error`` rows
        # for completions whose delivery was ABANDONED. Both are additions to
        # blocks a consumer already parses, on a ``kind`` it already knows, and
        # both are consumed by the Launcher in the same wave. The reason
        # ``state`` had to be added at all is worth recording: without it an
        # ``error`` dispatch — which ``pending_deliveries`` selects and delivers
        # exactly like a successful one — was distinguishable from success only
        # in the prose body, so a consumer would have had to sentence-match to
        # phrase an honest notification. That is precisely what the typed marker
        # exists to prevent, so the fix belongs on the wire rather than in the
        # reader.
        #
        # 53 (Activity ownership correction, 2026-08-04) REMOVES the
        # ``mcp_server`` running-work source and its rows. A connected MCP
        # transport is reusable capability infrastructure, not a background
        # task: it can stay warm after the admitting turn settles and several
        # persona instances can share the same profile/server. It therefore has
        # no single truthful owner and must not make an idle runtime say
        # "1 running". Active calls remain visible on their owning chat turn's
        # tool trace. This is a wire removal, so the contract and Launcher pin
        # move together under the removal rule recorded at 46.
        #
        # 54 (S70 persona-instance wire prune, 2026-08-09) REMOVES six keys from
        # every ``persona_instances`` row. Two were duplicate ALIASES that
        # projected byte-identical values to the canonical key beside them —
        # ``current_work_assignment_id`` (= ``current_assignment_id``) and
        # ``attached_task_id`` (= ``current_task_id``); ``attached_task_id`` also
        # leaves the ``state_patches`` projection in this wave, because a patch
        # lane that kept emitting a key the full rebuild dropped would make the
        # two lanes disagree about the row's shape. Four were writer-less since
        # the worker/goal lanes died, with no consumer past a Launcher model copy:
        # ``context_receipt_id``, ``compression_receipt_id``, ``tool_budget_used``,
        # ``watchdog_warning_count`` (these four also leave ``PersonaInstance``
        # itself; ``serde._coerce`` ignores the stale keys still on disk).
        #
        # Two fields the deferred-debt ledger grouped with them deliberately DID
        # NOT move, and the distinction is the point of this entry: writer-less is
        # not the same as reader-less. ``token_budget_used`` feeds the Launcher's
        # token-total fallback (``totalTokens ?? tokenBudgetUsed``) and
        # ``last_heartbeat_at`` is read by the Launcher's roster-recency tiebreak
        # AND re-emitted on the Agent Gateway state frame AND read here by
        # ``classify_orphan_persona_instances`` as the heartbeat HOLD. Dropping
        # either would silently retire a live consumer, so retiring them is a
        # reader-side decision that needs its own ruling — not a wire cleanup.
        # This is a wire removal, so the contract and Launcher pin move together
        # under the removal rule recorded at 46.
        #
        # 54 KEPT (running_work contract/ambient split, 2026-08-09) — the
        # ``running_work`` section stops folding MACHINE-LOCAL state into its
        # per-source ``detail`` prose, gains a typed ``live_enrichment_error`` on
        # a source entry, and gains a sibling ``ambient`` block naming the
        # resolved background-work home. The two-part rule recorded at "52 KEPT"
        # answers it, and the FIRST part needs stating carefully, because a key
        # does stop appearing on some entries:
        #
        # (a) Nothing LEAVES the wire. ``detail`` is not removed — it keeps its
        # key, its type and its documented meaning ("bounded operator detail,
        # WHEN hermes attached one"), and on the entries a consumer actually
        # renders it from (``unavailable`` lanes, where it has always been a bare
        # exception class name) it is byte-identical. Its presence was ALREADY
        # conditional on both sides: three of the five lanes ship ``ok`` entries
        # with no ``detail`` today, and the Launcher models it as
        # ``_string(json['detail'], fallback: '')``. What changes is which values
        # an optional diagnostic takes on the ``ok`` entries of two lanes — not
        # the schema. That is categorically different from 46/49/53/54, each of
        # which deleted a key or a section a consumer modelled and could no
        # longer find.
        #
        # (b) The additions are "merely unread", not "invisible". ``sources`` is
        # parsed as a MAP with named-key reads — the constraint the WP-H2 ruling
        # put on the consumer, for exactly this reason — so an unknown
        # ``live_enrichment_error`` is ignored; ``ambient`` is a new sibling key
        # on a section the Launcher already parses field-by-field, so a
        # pinned-54 reader ignores it rather than fail-closing.
        #
        # Why it had to move at all: the old ``detail`` concatenated contract
        # with ambient filesystem state, and the filesystem half was perturbed by
        # the projection's OWN lazy import (``_collect_chat_turns`` reaches a
        # tool singleton whose constructor creates ``state.db``), so the same
        # producer emitted two different strings for identical work depending on
        # import order. A wire field no consumer can rely on and no test can pin
        # honestly is worse than no field.
        #
        # 54 KEPT, THIRD TIME (EG-3.1, the persisted core, 2026-08-17) — the
        # parity envelope gains ``core_source`` (+ ``core_stale``) and the office
        # rows gain ``actors_unreadable``. The two-part rule recorded at
        # "52 KEPT" answers both, and the SECOND part needs stating carefully
        # because the fixtures are the evidence:
        #
        # (a) Nothing LEAVES the wire. No key, no section, no value a consumer
        # models is removed or narrowed.
        #
        # (b) Neither addition is "invisible rather than merely unread".
        # ``core_source`` is emitted ONLY when a persisted core was available to
        # decide between (see ``core_cache.label_core``) — a build in a root that
        # has never held one answers no such question and stamps nothing, which
        # is why every committed producer fixture is byte-unchanged by this
        # landing. The precedent for the shape is one file over: ``read_model``
        # already stamps ``parity.frame_source`` under the same reasoning ("one
        # location, additive, no contract bump"), and the ``delta_patches``
        # hydrate marker is absent when its lane is off for exactly this
        # golden-stability reason. ``actors_unreadable`` is a new key on an office
        # row the Launcher parses field-by-field, alongside the
        # ``actors_truncated`` it already ignores.
        #
        # The STALE label deliberately reuses an existing field rather than
        # adding one: a stale-served core sets ``parity.freshness.state =
        # "stale"``, which ``MissionSnapshotEnvelope`` already parses and
        # ``health()`` already maps to ``MissionSnapshotHealth.stale``. So the
        # honesty half of EG-3.1 needs no launcher change and no bump — an
        # unvalidated projection reads as stale on a pinned-54 launcher today.
        #
        # 54 KEPT (AX2, the writerless assignment lane, 2026-08-31) — THE FIRST
        # KEPT RULING OVER A DEPARTURE, written at length because rule (a)
        # recorded at 46 ("anything that LEAVES the wire bumps") is unconditional
        # on its face and this entry does not pretend otherwise. Three things
        # leave: the whole ``persona_assignments`` block (with S8's
        # ``recent_ref`` eviction pointer), ``persona_instance_runtime
        # .assignment_store_enabled`` (constant ``true`` since it was written),
        # and top-level ``warnings``.
        #
        # Rule (a) exists to stop ONE failure: a consumer that modelled a key
        # keeps parsing, silently receives nothing, and a real surface goes blank
        # with no signal. Here that failure is not merely unlikely — it is PINNED
        # ABSENT IN THE CONSUMER'S OWN SUITE. The launcher deleted every read of
        # the block in the same wave (``6bf48ba26``: the model, the decoder, the
        # roster-fold parameter and five always-null fields) and keeps
        # ``mission_agent_instance_test.dart`` feeding a payload that still
        # CARRIES the block while asserting nothing in it reaches the instance.
        # ``warnings`` never had a launcher reader at all — the bridge mapper's
        # forward list does not carry it, so it never reached
        # ``MissionControlSnapshot.fromJson``, and its one code
        # (``agent_already_assigned``) is already a launcher tombstone row.
        #
        # And the bump is the RISKIER move here, which is what settles it.
        # ``MissionSnapshotEnvelope.health()`` requires EXACT equality, so 55
        # against a pinned-54 launcher is ``newerContract`` — and
        # ``MissionFrameTrust`` maps that to ``mayWrite == false``: an operator
        # who cannot delete or place anything until the launcher's own pin lands.
        # Moving the number would spend a live operator write-gate to defend a
        # read that provably does not exist; keeping it means neither repo has to
        # move in lockstep at all.
        #
        # What this entry does NOT license: a departure whose consumer-side
        # absence is believed rather than measured and pinned. The evidence
        # standard is the launcher's test, not the removal's tidiness. The
        # goldens still move and still have to be mirrored — see
        # ``tests/fixtures/stream_frames/README.md``.
        #
        # The number itself lives at module scope as
        # :data:`SNAPSHOT_CONTRACT_VERSION` so that consumers derive it instead
        # of restating it; the history above stays here, where the rulings are.
        "contract_version": SNAPSHOT_CONTRACT_VERSION,
        "generated_at": data.get("generated_at"),
        "redaction_mode": getattr(cfg, "redaction_mode", "strict"),
        "redaction_observed": _redaction_observed(data),
        "build_ms": int(max(0.0, (time.perf_counter() - build_started)) * 1000),
        # Additive per-section wall-time breakdown (ms) alongside build_ms — a
        # small, stable, lowercase-keyed dict so a reader can see where a slow
        # build spent its time. Held BY REFERENCE so the caller can record the
        # parity section's own duration after this envelope is assembled.
        "sections_ms": sections_ms if sections_ms is not None else {},
        "snapshot_bytes": _snapshot_payload_size(data),
        "event_log_bytes": int(watermark.get("event_offset") or 0),
        "projection_age_ms": _projection_age_ms(last_ts),
        "watermark": watermark,
        "runtime_root": _runtime_root_identity(),
        "resolution": resolution_payload(resolution),
        "profile": _runtime_profile_identity(),
        "capabilities": [
            "operator_capabilities",
            "server_minted_chat_sessions",
        ],
        "freshness": {
            "state": "fresh",
            "stale_after_seconds": 30,
            "generated_at": data.get("generated_at"),
        },
        "completeness": completeness,
        "drops": drop_samples,
        "warnings": warnings,
    }


def _snapshot_payload_size(data) -> int:
    try:
        return len(json.dumps(to_jsonable(data), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0


def _projection_age_ms(last_event_ts) -> int | None:
    if last_event_ts is None:
        return None
    try:
        if isinstance(last_event_ts, datetime):
            ts = last_event_ts
        else:
            text = str(last_event_ts)
            ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
        current = now()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=current.tzinfo)
        return max(0, int((current - ts.astimezone(current.tzinfo)).total_seconds() * 1000))
    except Exception:
        return None


def _runtime_root_identity() -> dict:
    text = str(paths.store_root()).replace("\\", "/")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return {
        "fingerprint": digest,
        "label": _safe_repo_scope_label(text),
    }


def _runtime_profile_identity() -> dict:
    try:
        from ..profile_context import active_profile_name

        name = active_profile_name()
    except Exception:
        name = None
    safe = _safe_model_label(str(name)) if name else None
    return {"name": safe or "default"}
