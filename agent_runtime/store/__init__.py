"""The agent-runtime stores — personas, workspaces, realms, and the historical
run / incident readers (the package map, rule 16).

Entry points and the modules to open, at most three:

* ``WorkspaceStore.set_active`` (``scope_activation``, the CLI) → ``workspaces``
  → ``base`` (the compare-and-set, the pointer write, the scope patch).
* ``WorkspaceStore.delete`` → ``workspaces`` → ``realms`` (membership + ledger
  save) → ``base``; ``board_store`` is an inbound package.
* ``RealmStore.tombstone_skill`` (``skills delete``) → ``realms`` → ``ledgers``
  → ``base``.
* ``AgentStore.save`` (``ensure_persisted_personas``, ``agent create``) → ``base``.
* The ledger questions (``realm_sync``, ``realm_revert``, ``default_scope``) →
  ``ledgers``.

Modules, lowest layer first (no module imports one above it — W0-G6):

==========  ======  ===========================================================
module      layer   owns
==========  ======  ===========================================================
ledgers     policy  skill tombstones, workspace lifts, ``prune_settled_ledger``,
                    ``ledger_time``, the two caps, the two selection normalizers
base        stores  the model files (``_write_model`` — the ONE writer), the
                    slug / display-name bounds, the active-pointer
                    compare-and-set + its scope patch, ``AgentStore``,
                    ``RunStore``, ``IncidentStore``, ``ACTIVE_RUN_STATES``
realms      stores  ``RealmStore``
workspaces  stores  ``WorkspaceStore`` (imports ``realms`` for the delete cascade)
==========  ======  ===========================================================

``TaskStore`` is the permanent ``task_store_stub.TaskStoreStub`` alias (ruling
R-3): upstream-owned readers resolve the name here, so it never moves.

Stores written: the model files under ``paths.store_root()`` (agents,
workspaces, realms, the two active pointers) — ``base._write_model`` only.
"""

from __future__ import annotations

from agent_runtime.store.ledgers import (  # noqa: F401 — the package's export floor
    active_skill_tombstones,
    DELETED_WORKSPACE_LEDGER_CAP,
    ledger_time,
    lift_deleted_workspace,
    prune_settled_ledger,
    SKILL_TOMBSTONE_LEDGER_CAP,
    skill_tombstone_matches,
    skill_tombstoned,
    workspace_lift_is_active,
    _normalize_agent_selection,
    _normalize_skill_selection,
    _prune_skill_tombstones,
    _prune_workspace_lifts,
)
from agent_runtime.store.base import (  # noqa: F401 — the package's export floor
    ACTIVATION_APPLY,
    ACTIVATION_DUPLICATE,
    ACTIVATION_SUPERSEDED,
    ACTIVE_RUN_STATES,
    AgentStore,
    apply_activation,
    IncidentStore,
    read_model_json,
    read_pointer,
    RunStore,
    _dedupe_ids,
    _emit_active_scope_patch,
    _list_models,
    _parse_intent_basis,
    _read_model,
    _resolve_activation_write,
    _safe_display_name,
    _slugify,
    _write_model,
)
from agent_runtime.store.realms import (  # noqa: F401 — the package's export floor
    RealmStore,
)
from agent_runtime.store.workspaces import (  # noqa: F401 — the package's export floor
    WorkspaceStore,
)
from agent_runtime.task_store_stub import TaskStoreStub as TaskStore  # noqa: F401 — ruling R-3

__layer__ = "stores"
