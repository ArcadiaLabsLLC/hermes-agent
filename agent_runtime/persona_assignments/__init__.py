"""The persona-assignment package — the package map (program rule 16).

Entry points (what calls in): ``PersonaInstanceStore`` (the roster store every
persona lane reads and writes), ``PersonaAssignmentStore`` (the assignment
READ/CLOSE side), and the identity helpers most of the tree takes —
``canonical_persona_instance_id``, ``persona_instance_id_for``,
``persona_chat_session_id_for``, ``persona_instance_display_name``,
``normalize_persona_id``, ``safe_assignment_token`` / ``safe_assignment_text``
(those two now live in ``agent_runtime.serde``; re-exported here).

The store is COMPOSED: ``store`` holds the row I/O and the class, and each lane
module holds one verb family as functions over the store, bound onto the class
as methods (``PersonaInstanceStore.open_chat is chat_binding.open_chat``), so a
caller — or a test patching a class attribute — sees the class it always saw.

Modules, lowest layer first (no module imports one above it — W0-G6):

==============  ======  ========================================================
module          layer   owns
==============  ======  ========================================================
vocabulary      models  chat modes and the typed reasons the lane spends
errors          models  the store's three refusals
profile         policy  model / effort / skill-override validation
identity        policy  id derivations, chat-session ids and owners (no store)
summary         policy  wire summaries and tool-visibility detail
scan            stores  whole-roster scans, unreadable-row ledger, presence probe
retire          stores  the archive layout and the retire lane
steering        stores  the parent-set lane and its acyclic commit
replicate       stores  the realm-sync replication door
repair          stores  steering and chat-binding repairs
chat_binding    stores  open / refuse / clear / roll back a chat binding
profile_writes  stores  ``update_profile`` / ``set_backing_profile``
store           stores  ``PersonaInstanceStore``: rows, mint, events, bindings
lookups         stores  identity answers that read the roster
assignments     stores  ``PersonaAssignmentStore`` + the task-id migration
==============  ======  ========================================================

The assignment state sets and ``ACTIVE_LANE_STATES`` live in
``agent_runtime.states``, beside the worker states they overlap.

Stores written: ``paths.persona_instances_dir()`` (instance rows),
``paths.persona_assignments_dir()`` (assignment rows), the ``*_retire`` archive
batches and their receipts, and the event log.

Every name an importer takes from ``agent_runtime.persona_assignments`` is
re-exported below, so no importer changes with the package.
"""

from __future__ import annotations

from agent_runtime.models import (
    looks_like_persona_instance_id,
    PERSONA_INSTANCE_ID_PREFIX,
)

from agent_runtime.serde import (
    safe_assignment_text,
    safe_assignment_token,
    safe_optional_token,
)

from agent_runtime.states import (
    ACTIVE_ASSIGNMENT_STATES,
    TERMINAL_ASSIGNMENT_STATES,
)

from agent_runtime.tool_visibility import (
    resolve_tool_visibility,
)

from agent_runtime.persona_assignments.vocabulary import (
    CHAT_BINDING_CLEARED_REASON_DELETED,
    PERSONA_ROWS_UNREADABLE,
)

from agent_runtime.persona_assignments.errors import (
    PersonaInstanceRetireError,
    RetiredPersonaInstanceError,
    StaleModelOverrideWrite,
)

from agent_runtime.persona_assignments.profile import (
    _model_supports_reasoning_effort,
    _safe_skill_overrides,
)

from agent_runtime.persona_assignments.identity import (
    canonical_chat_instance_id,
    canonical_persona_instance_id,
    chat_session_is_foreign_to_instance,
    chat_session_owner_instance_id,
    is_canonical_persona_channel,
    normalize_persona_id,
    persona_chat_session_id_for,
    persona_instance_id_for,
    persona_instance_id_for_placement,
    row_is_canonical_persona_channel,
    _display_name_for_template,
    _normalize_instance_source_persona,
    _profile_id_for_persona_or_template,
)

from agent_runtime.persona_assignments.summary import (
    active_persona_instance_agent_summaries,
    persona_assignment_summary,
    persona_instance_summary,
    persona_instance_tool_detail,
    PERSONA_INSTANCE_VISIBILITY_FIELDS,
    persona_instance_visibility_ref,
    _profile_visibility_persona,
)

from agent_runtime.persona_assignments.scan import (
    PersonaAssignmentScan,
    PersonaInstanceScan,
    PersonaScanRefusal,
    reset_unreadable_instance_rows,
)

from agent_runtime.persona_assignments.retire import (
    retire_receipt_path,
    RETIRE_RECEIPTS_DIRNAME,
    retired_persona_instance_ids,
)

from agent_runtime.persona_assignments.store import (
    PersonaInstanceStore,
)

from agent_runtime.persona_assignments.lookups import (
    chat_session_owner_persona,
    normalize_persona_or_template_id,
    persona_id_from_instance_id,
    persona_instance_display_name,
    personas_equal,
    resolve_default_chat_session_id_for_instance,
    sender_scope_workspace_id,
)

from agent_runtime.persona_assignments.assignments import (
    migrate_retired_persona_assignment_task_ids,
    PersonaAssignmentStore,
)

__layer__ = "stores"

__all__ = [
    "ACTIVE_ASSIGNMENT_STATES",
    "active_persona_instance_agent_summaries",
    "canonical_chat_instance_id",
    "canonical_persona_instance_id",
    "CHAT_BINDING_CLEARED_REASON_DELETED",
    "chat_session_is_foreign_to_instance",
    "chat_session_owner_instance_id",
    "chat_session_owner_persona",
    "is_canonical_persona_channel",
    "looks_like_persona_instance_id",
    "migrate_retired_persona_assignment_task_ids",
    "normalize_persona_id",
    "normalize_persona_or_template_id",
    "persona_assignment_summary",
    "persona_chat_session_id_for",
    "persona_id_from_instance_id",
    "persona_instance_display_name",
    "persona_instance_id_for",
    "persona_instance_id_for_placement",
    "PERSONA_INSTANCE_ID_PREFIX",
    "persona_instance_summary",
    "persona_instance_tool_detail",
    "PERSONA_INSTANCE_VISIBILITY_FIELDS",
    "persona_instance_visibility_ref",
    "PERSONA_ROWS_UNREADABLE",
    "PersonaAssignmentScan",
    "PersonaAssignmentStore",
    "PersonaInstanceRetireError",
    "PersonaInstanceScan",
    "PersonaInstanceStore",
    "personas_equal",
    "PersonaScanRefusal",
    "reset_unreadable_instance_rows",
    "resolve_default_chat_session_id_for_instance",
    "resolve_tool_visibility",
    "retire_receipt_path",
    "RETIRE_RECEIPTS_DIRNAME",
    "retired_persona_instance_ids",
    "RetiredPersonaInstanceError",
    "row_is_canonical_persona_channel",
    "safe_assignment_text",
    "safe_assignment_token",
    "safe_optional_token",
    "sender_scope_workspace_id",
    "StaleModelOverrideWrite",
    "TERMINAL_ASSIGNMENT_STATES",
    "_display_name_for_template",
    "_model_supports_reasoning_effort",
    "_normalize_instance_source_persona",
    "_profile_id_for_persona_or_template",
    "_profile_visibility_persona",
    "_safe_skill_overrides",
]
