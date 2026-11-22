"""Workspace-scoping authority for the addressable dispatch roster.

Single source of truth for one question: which persona instances are
ADVERTISED to, and BARE-PERSONA-RESOLVED for, a lane operating inside a given
Mission Control workspace. A persona may be placed into more than one workspace
scene; the Runtime Situation HUD and the mission-chat target resolver must only
offer / count the placements that belong to the SENDER's workspace, or a
two-agent order fans out across duplicate placements in other workspaces (live
2026-07-23: a Neko order for two agents landed on sibling placements in
unrelated workspaces).

Semantics (the whole contract lives here):

- An instance's ``workspace_id`` pointer of ``None`` means RUNTIME-GLOBAL: a
  profile's own channel, an unseated agent's instance and any pre-pointer record
  carry no scene claim and are therefore visible/addressable in EVERY workspace.
- A non-None pointer is a "belongs to THIS workspace" claim: in scope only for
  the matching workspace.
- A scope of ``None`` (no active workspace at all) means everything is in scope
  — the resolver degrades to today's unscoped behaviour rather than hiding the
  whole roster.

This module scopes ADVERTISING and BARE-PERSONA resolution ONLY. It never
re-elects identity: explicit ``personainst_*`` targeting stays allowed
cross-workspace, and identity lookups (who steers whom) continue to resolve
against the full, unfiltered roster.

On top of workspace scoping it owns one rule for the addressable view:

- "A held hidden copy is not on any level" (:func:`exclude_held_copies`): a row the
  hidden-copy migration held machine-local (stamped ``adopted_from_global``, standing in no
  workspace) is never advertised to, nor bare-persona-resolved for, anyone; it is reachable by
  its handle only. RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT retired the two
  canonical-row rules that stood here ("global canonicals are not on the level", "placements
  shadow canonical") with the canonical predicate they took: nothing mints a hidden copy, an
  adopted one is an ordinary placed instance, and a bare-persona send with no instance in reach
  is placed or refused (``chat_turn_target``), so no residual fallback to a hidden copy is left.

The rule is a property of the ADDRESSABLE roster only; identity/steering lists
(``identity_roster``) always read the full set. It is a SEPARATE pure helper rather than
folded into :func:`scope_roster`, whose pinned contract is a purely additive filter that never
drops rows.

Pure and stdlib-only — no I/O, no harness imports — so the scoping table is
unit-testable in isolation (matches :mod:`agent_runtime.target_policy`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .serde import optional_text

__layer__ = "policy"


def effective_workspace_id(
    instance: Any, *, active_workspace_id: str | None
) -> str | None:
    """The workspace a lane effectively operates in.

    An instance's own ``workspace_id`` pointer wins; a runtime-global instance
    (no pointer) falls back to the ``active_workspace_id`` it is being viewed
    from. Returns ``None`` only when neither is set (no scene at all)."""

    return optional_text(getattr(instance, "workspace_id", None)) or optional_text(active_workspace_id)


@dataclass(frozen=True, slots=True)
class LaneWorkspace:
    """The workspace one lane operates in, and the name it is shown by.

    Both ``None`` when there is no scene at all. ``name`` alone is ``None`` when
    the id names no workspace the caller listed (a pointer to one since removed).
    """

    id: str | None = None
    name: str | None = None


def lane_workspace(
    instance: Any, *, active_workspace_id: str | None, workspaces: Iterable[Any]
) -> LaneWorkspace:
    """:func:`effective_workspace_id`, named from ``workspaces``.

    The one answer to "which workspace is this lane's turn in": what the agent
    is told (the Runtime Situation scope line) and what the turn's context
    record says both read it, so the two cannot name different workspaces.
    """

    scope_id = effective_workspace_id(instance, active_workspace_id=active_workspace_id)
    if scope_id is None:
        return LaneWorkspace()
    name = next(
        (
            optional_text(getattr(item, "name", None))
            for item in (workspaces or ())
            if getattr(item, "id", None) == scope_id
        ),
        None,
    )
    return LaneWorkspace(id=scope_id, name=name)


def instance_in_scope(
    candidate_workspace_id: str | None, scope_workspace_id: str | None
) -> bool:
    """True when a candidate placement is addressable from ``scope_workspace_id``.

    A runtime-global candidate (``None`` pointer) is visible in every workspace;
    a scene-bound candidate is visible only in its own workspace. When the scope
    itself is ``None`` (no active workspace), everything is in scope so the
    resolver never hides the whole roster."""

    scope = optional_text(scope_workspace_id)
    if scope is None:
        return True
    candidate = optional_text(candidate_workspace_id)
    return candidate is None or candidate == scope


def scope_roster(instances: Iterable[Any], *, scope_workspace_id: str | None) -> list:
    """Return the input roster filtered to the workspace scope, order preserved.

    Keeps every runtime-global row plus the rows bound to ``scope_workspace_id``;
    input order is preserved so the "On level" roster block and candidate
    enumeration stay stable. Never mutates or dedupes — a purely additive
    filter over addressing, not identity."""

    return [
        instance
        for instance in (instances or ())
        if instance_in_scope(getattr(instance, "workspace_id", None), scope_workspace_id)
    ]


def exact_scoped_instance_ids(
    instances: Iterable[Any], *, workspace_id: str | None
) -> list[str]:
    """Ids of live-store rows that explicitly belong to ``workspace_id``.

    This is intentionally stricter than :func:`scope_roster`: runtime-global
    rows and fallback visibility do not represent an agent placed in a workspace. Callers pass the active ``PersonaInstanceStore.list_all``
    rows, whose archive-never-delete retirement contract already excludes
    retired instances from the live directory.
    """

    wanted = optional_text(workspace_id)
    if wanted is None:
        return []
    return sorted(
        {
            instance_id
            for instance in (instances or ())
            if optional_text(getattr(instance, "workspace_id", None)) == wanted
            and (instance_id := optional_text(getattr(instance, "id", None))) is not None
        }
    )


def is_held_copy(instance: Any) -> bool:
    """A hidden copy the migration held machine-local: stamped, and standing in no workspace."""

    return bool(getattr(instance, "adopted_from_global", None)) and optional_text(
        getattr(instance, "workspace_id", None)
    ) is None


def exclude_held_copies(instances: Iterable[Any]) -> list:
    """Drop every held hidden copy (:func:`is_held_copy`); order preserved, inputs never mutated."""

    # MUTATION: return the input unfiltered and test_a_held_copy_is_never_addressable reddens.
    return [instance for instance in (instances or ()) if not is_held_copy(instance)]


def addressable_roster(
    instances: Iterable[Any],
    *,
    scope_workspace_id: str | None,
) -> list:
    """The roster a lane may ADVERTISE / bare-persona-resolve, order preserved.

    The single composition every addressable surface uses so the rule lives in
    exactly one place: :func:`scope_roster` narrows to the sender's workspace,
    then :func:`exclude_held_copies` drops the held hidden copies. Never mutates
    inputs. The FULL roster (for identity/steering) must be kept separately by the
    caller — this returns only the addressable view.
    """

    return exclude_held_copies(scope_roster(instances, scope_workspace_id=scope_workspace_id))
