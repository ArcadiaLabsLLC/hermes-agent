"""The persona-assignment vocabulary: the assignment state sets, the chat modes an
instance holds only while a chat is open, and the typed reasons the lane spends.

Separate because every other module of the package reads these words and none
of them may own them.
"""

from __future__ import annotations



__layer__ = "models"

__all__ = [
    "ACTIVE_ASSIGNMENT_STATES",
    "CHAT_BINDING_CLEARED_REASON_DELETED",
    "PERSONA_ROWS_UNREADABLE",
    "TERMINAL_ASSIGNMENT_STATES",
    "_BINDING_REPAIR_REASON",
    "_CHAT_MODES",
]


TERMINAL_ASSIGNMENT_STATES = frozenset({"completed", "blocked", "cancelled"})

# Modes that only exist because the instance is holding a chat open; once its
# last chat pointer is cleared the row demotes back to a plain configured agent.
_CHAT_MODES = frozenset({"chat", "free_floating"})

# Typed reasons carried on ``persona_instance.chat_binding_cleared``.
_BINDING_REPAIR_REASON = "session_missing_from_session_db"
CHAT_BINDING_CLEARED_REASON_DELETED = "chat_deleted"

#: The one word the persona lane spends when an arm cannot READ the rows it was
#: asked to decide about. Minted in exactly ONE place
#: (:meth:`PersonaScanRefusal.for_scan`) so no arm can quietly reuse another
#: arm's sentence for a condition it does not describe (C16).
PERSONA_ROWS_UNREADABLE = "persona_rows_unreadable"


ACTIVE_ASSIGNMENT_STATES = frozenset({"queued", "assigned", "running", "waiting_on_tool", "waiting_on_proof", "needs_input"})
# S56 removed ``_worker_carries_live_binding``. It decided whether a WORKER row
# could stamp its ``task_bound`` binding onto a persona instance during
# derivation. Both of its inputs are gone: the worker session store was deleted
# (nothing can write a worker row, and the live runtime root carries no
# ``worker_sessions/`` directory at all), and ``build_snapshot`` had already
# been passing a ``workers = []`` literal into the derivation for two waves — so
# on the live tree the "carries" branch could never be taken and every persona
# fell through to the configured/idle reset. That reset is now unconditional in
# ``PersonaInstanceStore.ensure_for_personas``; the 2026-07-08 regression this
# predicate was written to fix (dead workers re-stamping a settled mission onto
# the instance) cannot recur, because there are no worker rows to re-stamp from.
