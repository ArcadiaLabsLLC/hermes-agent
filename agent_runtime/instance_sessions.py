"""Which sessions in one chat store belong to one persona instance.

A session belongs to an instance when its ``model_config`` names it
(``persona_instance_id``), else when its id is the root the instance minted
(``persona_chat_<instance>_<12 hex>``, ``chat_session_owner_instance_id``). One
predicate, shared by the history list, the first-bind stamp's legacy-row guard
and the chat-head migrate verb, so the three cannot disagree about whose chat a
row is.
"""

from __future__ import annotations

from typing import Any

__layer__ = "stores"

__all__ = ["instance_session_clause", "instance_session_ids"]


def instance_session_clause(instance_id: str) -> tuple[str, list[str]]:
    """The SQL predicate (and its arguments) for *instance_id*'s sessions."""

    return ("(json_extract(model_config,'$.persona_instance_id')=? OR "
            "(COALESCE(json_extract(model_config,'$.persona_instance_id'),'')='' AND id GLOB ?))",
            [instance_id, _minted_session_glob(instance_id)])


def instance_session_ids(db: Any, instance_id: str, *, limit: int | None = None) -> list[str]:
    """Ids of *instance_id*'s sessions in *db*, any source, oldest first.

    Rows whose ``model_config`` is not JSON are skipped by the predicate's own
    guard rather than raising inside ``json_extract``.
    """

    clause, args = instance_session_clause(instance_id)
    sql = ("SELECT id FROM sessions WHERE (model_config IS NULL OR json_valid(model_config)) AND "
           + clause + " ORDER BY started_at, id")
    if limit is not None:
        sql += " LIMIT ?"
        args = [*args, int(limit)]
    return [str(row["id"]) for row in db._read_all(sql, args)]


def _minted_session_glob(instance_id: str) -> str:
    """GLOB for ``persona_chat_<instance>_<12 hex>`` (``chat_session_owner_instance_id``)."""

    escaped = "".join(f"[{ch}]" if ch in "*?[" else ch for ch in instance_id)
    return "persona_chat_" + escaped + "_" + "[0-9a-fA-F]" * 12
