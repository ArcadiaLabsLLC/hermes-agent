"""The persona-assignment package — the package map (program rule 16).

Entry points (what calls in): ``PersonaInstanceStore`` (the roster store every
persona lane reads and writes), ``PersonaAssignmentStore`` (the assignment
READ/CLOSE side), and the identity helpers most of the tree takes —
``canonical_persona_instance_id``, ``persona_instance_id_for``,
``persona_chat_session_id_for``, ``persona_instance_display_name``,
``normalize_persona_id``, ``safe_assignment_token`` / ``safe_assignment_text``.

Modules, lowest layer first (no module imports one above it — W0-G6):

============  ======  ==========================================================
module        layer   owns
============  ======  ==========================================================
vocabulary    models  assignment state sets, chat modes, typed lane reasons
errors        models  the store's three refusals
tokens        policy  token / text sanitizers, skill-override normalizer
profile       policy  model-override and reasoning-effort validation
identity      policy  id derivations, chat-session ids and owners (no store)
summary       policy  wire summaries and tool-visibility detail
scan          stores  whole-roster scans, unreadable-row ledger, presence probe
retire        stores  the retired-instance archive layout and receipts
store         stores  ``PersonaInstanceStore``
lookups       stores  identity answers that read the roster
assignments   stores  ``PersonaAssignmentStore`` + the task-id migration
============  ======  ==========================================================

Stores written: ``paths.persona_instances_dir()`` (instance rows),
``paths.persona_assignments_dir()`` (assignment rows), the ``*_retire`` archive
batches and their receipts, and the event log.

Every name an importer takes from ``agent_runtime.persona_assignments`` today is
re-exported below, so no importer changes with the package.
"""

from __future__ import annotations

from agent_runtime.models import PERSONA_INSTANCE_ID_PREFIX, looks_like_persona_instance_id

from agent_runtime.tool_visibility import resolve_tool_visibility

from agent_runtime.persona_assignments.vocabulary import (
    ACTIVE_ASSIGNMENT_STATES,
    CHAT_BINDING_CLEARED_REASON_DELETED,
    PERSONA_ROWS_UNREADABLE,
    TERMINAL_ASSIGNMENT_STATES,
)

from agent_runtime.persona_assignments.errors import (
    PersonaInstanceRetireError,
    RetiredPersonaInstanceError,
    StaleModelOverrideWrite,
)

from agent_runtime.persona_assignments.tokens import (
    safe_assignment_text,
    safe_assignment_token,
    safe_optional_token,
    _safe_skill_overrides,
)

from agent_runtime.persona_assignments.profile import (
    _model_supports_reasoning_effort,
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
