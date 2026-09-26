"""Durable store for DETACHED agent-to-agent dispatches (``wait: false``) — the package map, rule 16.

A dispatch is one ``agent_chat_send(wait=false)``: the sender's turn returns
immediately with a handle, the target's turn runs on a background executor, and
the reply is delivered back into the SENDER's chat session later as a forged
turn when that session is idle (see :mod:`agent_runtime.dispatch_delivery`).

Entry points and the modules to open, at most three:

* ``record_dispatch`` / ``record_completion`` (``tools/agent_chat_*``) →
  ``writes`` → ``db``.
* ``claim_delivery`` … ``mark_delivered`` (``dispatch_delivery``'s drain) →
  ``delivery`` → ``db``; ``rearm_delivery`` (the CLI repair verb) likewise.
* ``restore_undelivered_dispatches`` (``serve/boot_phases``) → ``delivery`` →
  ``writes`` (the settle) → ``db``.
* ``running_dispatches`` / ``remote_media_completions`` (``running_work``,
  ``media_handles``) → ``db``.

Modules, lowest layer first (no module imports one above it — W0-G6):

===========  ======  ============================================================
module       layer   owns
===========  ======  ============================================================
models       models  the row vocabulary (states, delivery states, reasons, re-arm
                     outcomes, bounds), row ↔ dict, the media-map shape check
supervision  stores  which dispatch ids a live supervisor in THIS process still
                     answers for (the tools lane writes it, ``db`` reads it)
db           stores  the one database: path, connect, schema + migrations, the
                     always-close transaction, the read-only query and the six
                     projections, the owner identity, the event append
writes       lanes   ``record_dispatch`` / ``record_completion`` + ``_prune`` and
                     the throttled backlog report
delivery     lanes   the delivery-state machine and the boot sweep
===========  ======  ============================================================

No module here imports ``tools.agent_chat_dispatch``: the supervisors'
process-local registry lives in ``supervision`` (they write it, ``db`` reads it),
so the store never reaches up into the tools lane (W0-G6); the tools lane calls
``record_completion`` downward.

Why a durable store and not an in-memory record map
---------------------------------------------------
The whole value of the lane is that the sender does not have to sit still. That
means the completion can land while the sender is mid-turn, and it means the
process can die between "the target answered" and "the sender was told". An
in-memory handle loses the answer in both cases, silently — the sender simply
never hears back and has no way to tell that from "they are still working".

So this reuses the ``async_delegation`` durable protocol WHOLESALE rather than
inventing a second one:

* ``delivery_state`` ∈ ``pending | delivered | dropped`` — the row's own record
  of whether the sender has actually been told.
* An expiring **claim** (:data:`CLAIM_EXPIRY_SECONDS`) so competing consumers —
  and, after a crash, the same consumer on the next boot — cannot double-deliver
  a completion or strand one behind a dead claimant.
* An attempt cap (:data:`MAX_DELIVERY_ATTEMPTS`) so an undeliverable row
  converges to a terminal ``dropped`` instead of replaying on every restart
  forever.
* Owner **PID + process start time**, because a bare PID is not identity: the
  kernel recycles numbers, and this repo has already been bitten by a recycled
  one landing on an unrelated process.
* Restore-on-boot stamps ``restored=True`` and requires POSITIVE ownership proof
  before delivery (#64484): a row restored from a previous process names the
  chat root it must be delivered into, and the drain re-proves that root is a
  real, current chat session before forging anything into it. Absence of
  disproof is not proof.

Where the database lives — and why that is not ``get_hermes_home()``
--------------------------------------------------------------------
``persona_profile_context`` flips ``HERMES_HOME`` PROCESS-GLOBALLY for the
duration of a persona turn, and a dispatch is *made from inside* such a turn.
Resolving the database through the ambient home at write time would persist an
in-flight dispatch into the persona profile's database — which the serve drain,
the Activity projection and the operator never open. That is the exact failure
:func:`agent_runtime.profile_home.get_hermes_background_work_home` was extracted to close,
so this module resolves through that ONE authority and never re-derives it.

Every mutation emits a registered EventLog event
-------------------------------------------------
``dispatch.recorded`` / ``dispatch.completed`` / ``dispatch.delivered`` /
``dispatch.dropped``. This is the standing store rule, not decoration: the
stream and read-model pipeline are watermark-gated on the EventLog, so a store
write with no event is invisible to every consumer until an unrelated event
happens to advance the offset. Payloads are bounded well inside the 4096-byte
cap — summaries, never transcripts.
"""

from __future__ import annotations

from agent_runtime.dispatch_store.models import (  # noqa: F401 — the package's export floor
    ASK_LIMIT,
    CLAIM_EXPIRY_SECONDS,
    DELIVERY_DELIVERED,
    DELIVERY_DROPPED,
    DELIVERY_PENDING,
    DROP_REASON_ATTEMPT_CAP,
    DROP_REASON_FORGE_REJECTED,
    ERROR_KIND_DISPATCH_STORE_UNAVAILABLE,
    MAX_DELIVERY_ATTEMPTS,
    MEDIA_HANDLE_LIMIT,
    MEDIA_MAP_LIMIT,
    MEDIA_REFERENCE_LIMIT,
    mint_dispatch_id,
    REARM_ALREADY_DELIVERED,
    REARM_ERROR_KINDS,
    REARM_NOT_DROPPED,
    REARM_NOT_FOUND,
    REARM_OUTCOME_BY_STATE,
    REARM_REARMED,
    REMOTE_UNREACHABLE_REASON,
    REPLY_LIMIT,
    STATE_COMPLETED,
    STATE_ERROR,
    STATE_RUNNING,
    STATE_UNKNOWN,
    TERMINAL_STATES,
    _MAX_RETAINED_TERMINAL,
    _media_rows,
    _RETENTION_SECONDS,
    _row_to_dict,
    _SELECT,
    _TABLE,
)
from agent_runtime.dispatch_store.db import (  # noqa: F401 — the package's export floor
    dispatch_db_path,
    get_dispatch,
    list_dispatches,
    pending_deliveries,
    remote_media_completions,
    running_dispatches,
    undeliverable_dispatches,
    _add_missing_column,
    _connect,
    _DB_LOCK,
    _emit,
    _initialize_schema,
    _owner_identity,
    _query,
    _supervised_here,
    _transaction,
)
from agent_runtime.dispatch_store.writes import (  # noqa: F401 — the package's export floor
    record_completion,
    record_dispatch,
    _backlog_report_due,
    _BACKLOG_REPORT_INTERVAL_SECONDS,
    _backlog_report_state,
    _completion_events,
    _completion_result,
    _completion_update,
    _prune,
)
from agent_runtime.dispatch_store.delivery import (  # noqa: F401 — the package's export floor
    claim_delivery,
    drop_delivery,
    mark_delivered,
    rearm_delivery,
    release_delivery_claim,
    restore_undelivered_dispatches,
    set_dispatch_owner,
)
__all__ = [
    "CLAIM_EXPIRY_SECONDS",
    "DELIVERY_DELIVERED",
    "DELIVERY_DROPPED",
    "DELIVERY_PENDING",
    "DROP_REASON_ATTEMPT_CAP",
    "DROP_REASON_FORGE_REJECTED",
    "MAX_DELIVERY_ATTEMPTS",
    "REMOTE_UNREACHABLE_REASON",
    "REARM_ALREADY_DELIVERED",
    "REARM_NOT_DROPPED",
    "REARM_NOT_FOUND",
    "REARM_REARMED",
    "STATE_ERROR",
    "STATE_RUNNING",
    "STATE_UNKNOWN",
    "TERMINAL_STATES",
    "claim_delivery",
    "dispatch_db_path",
    "list_dispatches",
    "mark_delivered",
    "mint_dispatch_id",
    "pending_deliveries",
    "rearm_delivery",
    "record_completion",
    "record_dispatch",
    "remote_media_completions",
    "release_delivery_claim",
    "restore_undelivered_dispatches",
    "running_dispatches",
    "undeliverable_dispatches",
    "set_dispatch_owner",
]

__layer__ = "lanes"
