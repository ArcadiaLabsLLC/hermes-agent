"""The snapshot builder — the read-model frame (the package map, rule 16).

Entry points (what calls in):

* ``build.build_snapshot`` — the serve lanes, ``stream`` and the harness verbs
  build the frame.
* ``context.SNAPSHOT_CONTRACT_VERSION`` / ``snapshot_build_context_scope``.
* ``details.persona_instance_detail_for_id`` / ``persona_session_db_scope``.
* The summary rows other lanes project the same way (``board_summary_row``,
  ``office_summary_row``, the workspace/realm summaries).

Modules, lowest layer first (no module imports one above it — W0-G6):

==========  ======  ============================================================
module      layer   owns
==========  ======  ============================================================
context     models  the contract version, the build context
receipts    policy  build roles/callers, coalescing state, diagnostics
build_log   policy  the build's log lines and section timing
boards      stores  the boards projection
offices     stores  the offices projection (the actor cap: office_models)
summaries   stores  workspace/realm/agent/persona summaries, template memo
warnings    stores  ``PARITY_WARNINGS``: the frame's parity checks
envelope    stores  the parity envelope (its contract-version ledger lives in
                    02-runtime-data-and-shapes.md)
details     lanes   per-instance detail reads
sections    lanes   ``SnapshotFrameBuild`` and its ``SECTIONS``
build       lanes   ``build_snapshot``: consult, coalesce, lead, persist
==========  ======  ============================================================
"""

from __future__ import annotations

import time
from agent_runtime.profile_home import (
    available_profile_template_summaries as available_profile_templates,
)
from agent_runtime.office_store import OfficeStore
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.persona_instance_identity import classify_orphan_persona_instances
from agent_runtime.resolution import suspect_default_root
from agent_runtime.store import AgentStore
from agent_runtime.tool_visibility import _profile_readiness_for_visibility
from agent_runtime.snapshot import (  # noqa: F401 — every family, in the original definition order
    context,
    receipts,
    build_log,
    build,
    sections,
    envelope,
    boards,
    offices,
    warnings,
    details,
    summaries,
)
from agent_runtime.snapshot.context import (
    SNAPSHOT_CONTRACT_VERSION,
    SnapshotBuildContext,
    SnapshotSummary,
    snapshot_build_context_scope,
)
from agent_runtime.snapshot.receipts import (
    BUILD_CALLER_UNKNOWN,
    BUILD_ROLE_CACHE,
    BUILD_ROLE_LED,
    BUILD_ROLE_REUSED,
    BUILD_ROLE_RODE,
    BUILD_ROLE_SHARED_NEXT,
    BUILD_SECTIONS_WAIT_THRESHOLD_MS,
    _BUILD_COALESCE,
    _build_coalesce_state,
    _keyed,
    _persona_chat_history_frame,
    build_receipt_facts,
)
from agent_runtime.snapshot.build import _build_snapshot_uncoalesced, build_snapshot
from agent_runtime.snapshot.sections import _build_snapshot_in_runtime_scope
from agent_runtime.snapshot.envelope import parity_envelope, _snapshot_payload_size
from agent_runtime.snapshot.boards import (
    BOARD_CARD_DESC_LIMIT,
    MAX_BOARD_CARDS_PROJECTED,
    board_card_row,
    _board_parity_warnings,
    _boards_summary,
    board_summary_row,
)
from agent_runtime.snapshot.offices import (
    MAX_OFFICE_ACTORS_PROJECTED,
    office_actor_summary_row,
    _office_parity_warnings,
    _offices_summary,
    office_summary_row,
)
from agent_runtime.snapshot.warnings import _parity_warnings
from agent_runtime.snapshot.details import (
    _default_persona_session_db,
    persona_instance_detail_for_id,
    persona_session_db_scope,
)
from agent_runtime.snapshot.summaries import (
    _agent_summary,
    _available_persona_summary,
    _profile_persona_reconcile_tick,
    _profile_templates_cached,
    realm_summary,
    workspace_summary,
)


__layer__ = "lanes"

__all__ = [
    "AgentStore",
    "BOARD_CARD_DESC_LIMIT",
    "BUILD_CALLER_UNKNOWN",
    "BUILD_ROLE_CACHE",
    "BUILD_ROLE_LED",
    "BUILD_ROLE_REUSED",
    "BUILD_ROLE_RODE",
    "BUILD_ROLE_SHARED_NEXT",
    "BUILD_SECTIONS_WAIT_THRESHOLD_MS",
    "MAX_BOARD_CARDS_PROJECTED",
    "MAX_OFFICE_ACTORS_PROJECTED",
    "OfficeStore",
    "SNAPSHOT_CONTRACT_VERSION",
    "SnapshotBuildContext",
    "SnapshotSummary",
    "_BUILD_COALESCE",
    "_agent_summary",
    "_available_persona_summary",
    "board_card_row",
    "_board_parity_warnings",
    "_boards_summary",
    "_build_coalesce_state",
    "_build_snapshot_in_runtime_scope",
    "_build_snapshot_uncoalesced",
    "_default_persona_session_db",
    "_keyed",
    "office_actor_summary_row",
    "_office_parity_warnings",
    "_offices_summary",
    "parity_envelope",
    "_parity_warnings",
    "_persona_chat_history_frame",
    "_profile_persona_reconcile_tick",
    "_profile_readiness_for_visibility",
    "_profile_templates_cached",
    "realm_summary",
    "_snapshot_payload_size",
    "workspace_summary",
    "available_profile_templates",
    "board_summary_row",
    "build_receipt_facts",
    "build_snapshot",
    "classify_orphan_persona_instances",
    "load_agent_runtime_config",
    "office_summary_row",
    "persona_instance_detail_for_id",
    "persona_session_db_scope",
    "snapshot_build_context_scope",
    "suspect_default_root",
    "time",
]
