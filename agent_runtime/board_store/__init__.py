"""The Mission Board store — the single write chokepoint for the board domain (the package map, rule 16).

Hard invariants (``docs/mission_control/BOARD_DESIGN``): cards are planning
state and never carry or mutate mission records; archive-never-delete (archived
cards move to ``archive/`` and their ids join the board's ``archived_card_ids``
resurrection-guard ledger); merge-friendly ordering (a fractional ``order_key``
allocated between neighbours by ``board_order``, tiebreak by ``card_id``).

Entry points and the modules to open, at most three:

* ``add_card`` / ``edit_card`` / ``move_card`` (the CLI, ``tools/board_tool``)
  → ``store`` → ``card_mechanics`` → ``files``.
* ``archive_card`` / ``restore_card`` → ``store`` → ``files``.
* ``scan_all`` / ``scan_cards`` (``realm_sync``, ``snapshot.sections``,
  ``store.WorkspaceStore.delete``) → ``store`` → ``files``.
* ``adopt_remote_*`` / ``resolve_conflict`` (``board_sync``, the CLI) →
  ``adopt`` → ``files`` (the one-line delegation on ``BoardStore`` is not a hop).

Modules, lowest layer first (no module imports one above it — W0-G6):

==============  ======  =========================================================
module          layer   owns
==============  ======  =========================================================
models          models  ``BoardScan`` / ``CardScan``, the verb tokens,
                        ``ARCHIVED_LEDGER_CAP``, the text / title / actor / label
                        / checklist bounds, card sort, the idempotency-key grammar
files           stores  the board on disk: the two writers, where a card is, the
                        per-directory scans, the conflict guard, the locked
                        archive step
card_mechanics  stores  ``CardOrdering`` (the ONE ordering read; append /
                        allocate / rebalance) and ``IdempotencyReceipts``
                        (replay with typed refusals; record per board, per verb)
adopt           stores  the realm-pull arms: ``adopt_remote_board``,
                        ``adopt_remote_card``, ``resolve_conflict``
store           stores  ``BoardStore`` — the verbs; nothing imports it but the map
==============  ======  =========================================================

Stores written: ``<boards_root>/<board_id>/`` (``board.json``, ``cards/``,
``archive/``, ``conflicts/``, the idempotency receipts) — this package only.
"""

from __future__ import annotations

from agent_runtime.board_store.models import (  # noqa: F401 — the package's export floor
    ARCHIVED_LEDGER_CAP,
    BoardScan,
    CardScan,
    VERB_ADD_CARD,
    VERB_EDIT_CARD,
    VERB_MOVE_CARD,
    _order_key_of,
    _safe_actor,
    _safe_checklist,
    _safe_idempotency_key,
    _safe_labels,
    _safe_text,
    _safe_title,
    _sort_cards,
)
from agent_runtime.board_store.files import (  # noqa: F401 — the package's export floor
    archive_card_locked,
    board_id_of_archived_card,
    board_id_of_conflict,
    card_path_active,
    guard_card_conflict,
    locate_card,
    scan_active_cards,
    scan_archived_cards,
    scan_card_dir,
    _write_board,
    _write_card,
)
from agent_runtime.board_store.card_mechanics import (  # noqa: F401 — the package's export floor
    CardOrdering,
    IdempotencyReceipts,
)
from agent_runtime.board_store.adopt import (  # noqa: F401 — the package's export floor
    adopt_remote_board,
    adopt_remote_card,
    resolve_conflict,
)
from agent_runtime.board_store.store import (  # noqa: F401 — the package's export floor
    BoardStore,
)

__layer__ = "stores"
