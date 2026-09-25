"""Store exceptions → JSON-RPC error frames, as data (rule 12).

The four office write verbs each used to end in a hand-written ``except``
cascade mapping ``StaleRevision`` / ``NotFound`` / ``ArchiveUnreadable`` /
``SyncConflict`` / ``ClassKeyedPlacementRefused`` / ``ValueError`` to a
``(code, reason, data)`` triple. Each verb now declares its translation as a
TABLE of rows built here, and one walker (:func:`translate`) picks the row by
the exception's MRO — the most specific class first, which is the order the
cascades' ``except`` clauses encoded by hand.

A verb's table is its contract: the same store exception can mean different
things on different verbs (``SyncConflict`` is a guard refusing an upsert, and
"there is no such conflict" on ``resolve_conflict``), so the rows are per verb
and the SHAPES are shared. An exception no row names propagates unchanged —
exactly what an unlisted ``except`` did.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.serve_rpc.protocol import err

__layer__ = "policy"

__all__ = [
    "OfficeWriteScope",
    "Translation",
    "refusal",
    "translate",
]


@dataclass(frozen=True)
class OfficeWriteScope:
    """What a translated refusal names: the request id, the workspace, and the
    verb's own keys a row may carry into ``data`` (``actor_key``,
    ``expect_revision``, ``take`` …)."""

    rid: Any
    workspace_id: str
    fields: Mapping[str, Any] = field(default_factory=dict)


#: One row: the caught exception and the verb's scope in, an error frame out.
Translation = Callable[[BaseException, OfficeWriteScope], dict]


def refusal(
    code: int,
    reason: str | Callable[[BaseException], str],
    *,
    carry: tuple[str, ...] = (),
    message: Callable[[BaseException, OfficeWriteScope], str] | None = None,
) -> Translation:
    """The common row shape: ``code``, ``data = {reason, workspace_id, *carry}``.

    ``reason`` is a constant, or a function of the exception when the reason
    is the exception's own (``ArchiveUnreadable.code`` on a subclass).
    ``message`` defaults to ``str(exc)`` — the store's own sentence.
    """

    def row(exc: BaseException, scope: OfficeWriteScope) -> dict:
        data: dict[str, Any] = {
            "reason": reason(exc) if callable(reason) else reason,
            "workspace_id": scope.workspace_id,
        }
        data.update((key, scope.fields[key]) for key in carry)
        text = message(exc, scope) if message is not None else str(exc)
        return err(scope.rid, code, text, data)

    return row


def translate(
    exc: BaseException,
    table: Mapping[type[BaseException], Translation],
    scope: OfficeWriteScope,
) -> dict:
    """The error frame ``table`` names for ``exc``; re-raises an unnamed one."""

    for cls in type(exc).__mro__:
        row = table.get(cls)
        if row is not None:
            return row(exc, scope)
    raise exc
