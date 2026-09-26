"""Native persona-chat continuity primitives.

This module intentionally contains no CLI presentation logic.  Direct CLI
commands and long-lived ``harness serve`` processes share these exact lease,
mint-receipt, safe-history, and resident-actor primitives.

Package map (lane B3, sheet ``god-file-layout-sheets/persona_chat_continuity.md``
§1). Entry points are what the outside calls; everything else is reached only
from inside. Layers point down (models <- policy <- stores <- lanes <- wiring);
this map is ``stores`` because the highest layer it re-exports is ``stores``.

    agent_runtime/persona_chat_continuity/
      __init__.py          stores   this map; re-exports the importer and test names
      bounds.py            policy   the composed-user-content bound: per-part ceilings,
                                    ContentBoundNote / BoundedUserContent, _redacted
      wire.py              policy   THE wire boundary: native_wire_row, safe_native_*,
                                    record_wire_boundary_drift, native_history_revision
      lease.py             stores   the chat-root lease + the scopes a turn holds
                                    (tool_execution_scope, chat_root_session_key_scope),
                                    repair_orphaned_chat_turns
      mint_receipts.py     stores   PersonaChatMintReceiptStore and its Mint phases
                                    (precondition -> receipt -> early bind -> session ->
                                    meta -> title -> commit; retract), _atomic_json
      clarify_tickets.py   stores   CLARIFY_* words and PersonaChatClarifyTicketStore
      clarify_index.py     stores   ClarifyTicketIndex: the store's by-session pointer
                                    index (lookup/add/drop/rebuild/sweep), expired()
      runtime_registry.py  stores   ResidentPersonaChatRuntime + PersonaChatRuntimeRegistry,
                                    RUNTIME_STATES

    entry point                                          opens
    persona_chat_root_lease / repair_orphaned_chat_turns lease
    PersonaChatMintReceiptStore.mint                     mint_receipts (Mint)
    safe_native_history / native_wire_row                wire -> bounds
    bound_composed_user_content                          bounds
    PersonaChatClarifyTicketStore.*                      clarify_tickets -> clarify_index
    persona_chat_runtime_registry().acquire/finish       runtime_registry

The fd byte lock the lease and the mint take is ``agent_runtime.file_locks``'
``try_lock_fd`` / ``unlock_fd``. A test patches a name where it is BOUND
(``persona_chat_continuity.lease.unlock_fd``, ``...clarify_index._atomic_json``);
a patch on this package's attribute reaches no caller.
"""

from __future__ import annotations

from . import bounds, clarify_index, clarify_tickets, lease, mint_receipts, runtime_registry, wire
from .bounds import (
    BOUND_ACTION_DROPPED,
    BOUND_ACTION_TRUNCATED,
    BOUND_PART_CONTENT,
    BOUND_PART_MESSAGE,
    BOUND_PART_RUNTIME_CONTEXT,
    BOUND_PART_SKILL_PRELOAD,
    BOUND_PART_TOOL_ARGUMENTS,
    CONTENT_BOUND_PARTS,
    BoundedUserContent,
    ContentBoundNote,
    _MAX_ARGUMENTS,
    _MAX_CONTENT,
    _MAX_RUNTIME_CONTEXT_CONTENT,
    _MAX_USER_ROW_CONTENT,
    _bound_envelope,
    bound_composed_user_content,
)
from .clarify_index import ClarifyTicketIndex
from .clarify_tickets import (
    CLARIFY_TICKET_ANSWERED,
    CLARIFY_TICKET_OPEN,
    CLARIFY_TICKET_REBOUND,
    CLARIFY_TICKET_TTL_SECONDS,
    CLARIFY_TOKEN_PREFIX,
    PersonaChatClarifyTicketStore,
)
from .lease import (
    PersonaChatBusyError,
    _lease_paths,
    chat_root_session_key_scope,
    current_tool_execution_scope,
    persona_chat_root_lease,
    repair_orphaned_chat_turns,
    tool_execution_scope,
)
from .mint_receipts import PERSONA_CHAT_SESSION_SOURCE, Mint, PersonaChatMintReceiptStore, _atomic_json
from .runtime_registry import (
    RESIDENT_SIGNATURE_DIFF_RECEIPT,
    RUNTIME_STATES,
    PersonaChatRuntimeRegistry,
    ResidentPersonaChatRuntime,
    _signature_component_diff,
    initialize_persona_chat_runtime_registry,
    persona_chat_runtime_registry,
)
from .wire import (
    WIRE_BOUNDARY,
    WIRE_ROLE_ASSISTANT,
    WIRE_ROLE_NAMES,
    WIRE_ROLE_SYSTEM,
    WIRE_ROLE_TOOL,
    WIRE_ROLE_USER,
    WireBoundaryRow,
    native_history_revision,
    native_lineage_summary,
    native_wire_row,
    record_wire_boundary_drift,
    safe_native_history,
    safe_native_message,
)

__layer__ = "stores"

__all__ = [
    "BOUND_ACTION_DROPPED",
    "BOUND_ACTION_TRUNCATED",
    "BOUND_PART_CONTENT",
    "BOUND_PART_MESSAGE",
    "BOUND_PART_RUNTIME_CONTEXT",
    "BOUND_PART_SKILL_PRELOAD",
    "BOUND_PART_TOOL_ARGUMENTS",
    "CLARIFY_TICKET_ANSWERED",
    "CLARIFY_TICKET_OPEN",
    "CLARIFY_TICKET_REBOUND",
    "CLARIFY_TICKET_TTL_SECONDS",
    "CLARIFY_TOKEN_PREFIX",
    "CONTENT_BOUND_PARTS",
    "PERSONA_CHAT_SESSION_SOURCE",
    "RESIDENT_SIGNATURE_DIFF_RECEIPT",
    "RUNTIME_STATES",
    "WIRE_BOUNDARY",
    "WIRE_ROLE_ASSISTANT",
    "WIRE_ROLE_NAMES",
    "WIRE_ROLE_SYSTEM",
    "WIRE_ROLE_TOOL",
    "WIRE_ROLE_USER",
    "BoundedUserContent",
    "ClarifyTicketIndex",
    "ContentBoundNote",
    "Mint",
    "PersonaChatBusyError",
    "PersonaChatClarifyTicketStore",
    "PersonaChatMintReceiptStore",
    "PersonaChatRuntimeRegistry",
    "ResidentPersonaChatRuntime",
    "WireBoundaryRow",
    "bound_composed_user_content",
    "bounds",
    "chat_root_session_key_scope",
    "clarify_index",
    "clarify_tickets",
    "current_tool_execution_scope",
    "initialize_persona_chat_runtime_registry",
    "lease",
    "mint_receipts",
    "native_history_revision",
    "native_lineage_summary",
    "native_wire_row",
    "persona_chat_root_lease",
    "persona_chat_runtime_registry",
    "record_wire_boundary_drift",
    "repair_orphaned_chat_turns",
    "runtime_registry",
    "safe_native_history",
    "safe_native_message",
    "tool_execution_scope",
    "wire",
]
