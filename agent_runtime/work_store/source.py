"""The SOURCE contract — rows from the workspace's todo boards (dispatcher plan §2.1, stage B1).

A ``WorkSource`` reads rows at the board's tip and writes them only through the W2 writer
(``writer.Writer.apply``: one row op per commit, by ID, replayed on a lost race). Nothing is cached
across calls except the fetch. Every write returns the writer's ``Receipt`` or raises
``WorkRefused(reason)`` with a reason in :data:`REFUSALS`.

The tree, where it differs from the plan: a row carries ``heading`` (W1 ``grammar.Row``), so the
batching key is :func:`domain_of`, not a ``Row.domain`` field; a claimant is the writer's ``who``
string, wrapped as :class:`Claimant`; the receipt kinds are the writer's ``work.row_<op>``, so
``block`` logs ``row_set_status`` then ``row_release`` and ``done`` logs ``row_delete``
(:data:`RECEIPT_KINDS`). This module is the contract only; the production source over
``board.py`` + ``work/store.py::synced`` is built where the dispatcher first reads it (B2).
"""

from __future__ import annotations

from typing import Protocol

from .board import Board
from .grammar import Op, Row, RowRef, Status, domain_of
from .models import Claimant, Domain
from .reasons import Reason
from .writer import Receipt

__layer__ = "lanes"
__all__ = ["RECEIPT_KINDS", "REFUSALS", "Claimant", "Domain", "WorkSource", "domain_of"]

#: Every refusal a SOURCE method may raise (plan §2.1). ``slot_unbound``: this machine lacks the checkout.
REFUSALS: frozenset[Reason] = frozenset({
    Reason.ROW_GONE, Reason.ALREADY_TAKEN, Reason.NOT_CLAIMANT, Reason.ID_EXISTS,
    Reason.PUSH_CONTENDED, Reason.SLOT_UNBOUND, Reason.GRAMMAR_INVALID,
})

#: The receipt kind(s) each SOURCE write logs, in order — the writer's ``work.row_<op>``, one per commit.
RECEIPT_KINDS: dict[str, tuple[str, ...]] = {
    "claim": (f"work.row_{Op.CLAIM.value}",),
    "release": (f"work.row_{Op.RELEASE.value}", f"work.row_{Op.SET_STATUS.value}"),
    "block": (f"work.row_{Op.SET_STATUS.value}", f"work.row_{Op.RELEASE.value}"),
    "done": (f"work.row_{Op.DELETE.value}",),
    "append": (f"work.row_{Op.APPEND.value}",),
}


class WorkSource(Protocol):
    def boards(self, workspace_id: str) -> list[Board]:
        """One board per live slot, then the default brain's while its binding is live (W1)."""

    def rows(self, workspace_id: str, *, status: Status | None = None, slot: str | None = None,
             assignee: str | None = None) -> list[Row]:
        """Every row at the tip, filtered by status, slot and assignee token."""

    def ready(self, workspace_id: str) -> list[Row]:
        """``rows(status=READY)`` minus the rows already ``TAKEN``."""

    def claim(self, ref: RowRef, who: Claimant, request_id: str) -> Receipt:
        """Append ``**TAKEN <date> <who>**``; ``already_taken`` when another holds it."""

    def release(self, ref: RowRef, who: Claimant, status: Status, reason: str) -> Receipt:
        """Drop ``who``'s claim and set ``status`` with ``reason``; ``not_claimant`` for another's claim."""

    def block(self, ref: RowRef, who: Claimant, question: str, recommend: str) -> Receipt:
        """``BLOCKED <date>: owner decision — <question> · Recommend: <recommend>``, then release."""

    def done(self, ref: RowRef, who: Claimant, result: str) -> Receipt:
        """Delete the row; ``result`` goes in the commit body."""

    def append(self, board: Board, row: Row, request_id: str) -> Receipt:
        """Add ``row`` to its note; ``id_exists`` when the ID is already in the brain."""
