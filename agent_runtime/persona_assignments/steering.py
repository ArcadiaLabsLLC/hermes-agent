"""The living-graph steering lane: set, add, remove, detach and clear an
instance's parent set, release references to a departing parent, and the one
commit path that validates the graph stays acyclic before it writes.

Functions over a ``PersonaInstanceStore`` (composition — the class binds each
one as a method).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hermes_time import now

from agent_runtime.errors import PersonaInstancesUnreadable
from agent_runtime.models import (
    looks_like_persona_instance_id,
    PERSONA_INSTANCE_ID_PREFIX,
    PersonaInstance,
)
from agent_runtime.persona_assignments.identity import canonical_persona_instance_id
from agent_runtime.serde import dedupe_tokens, safe_optional_token

if TYPE_CHECKING:
    from agent_runtime.persona_assignments.store import PersonaInstanceStore

__layer__ = "stores"

__all__ = [
    "_apply_steer_edges",
    "_commit_steer",
    "_release_parent_references",
    "_validate_no_steering_cycle",
    "add_parent",
    "clear_parents",
    "detach_parents",
    "remove_parent",
    "set_parents",
    "steer",
]


def steer(
    store: PersonaInstanceStore,
    persona_instance_id: str,
    *,
    parent_instance_id: str | None,
    goal_id: str | None = None,
    detach: bool = False,
) -> PersonaInstance:
    """Back-compat single-parent re-route (Stage 77).

    Preserves the original ``--parent`` semantics EXACTLY: replace the whole
    steering set with the one given parent, or clear it on ``detach``. New
    multi-parent callers use :meth:`set_parents` / :meth:`add_parent` /
    :meth:`remove_parent` / :meth:`detach_parents`. This is a re-route (a
    STEER verb, ungated per 76D.3), never a create/kill.
    """
    if detach:
        return store.detach_parents(persona_instance_id)
    normalized_parent = safe_optional_token(parent_instance_id)
    if not normalized_parent:
        raise ValueError("parent_instance_id is required unless detach is set")
    return store.set_parents(persona_instance_id, [normalized_parent], goal_id=goal_id)


def set_parents(
    store: PersonaInstanceStore,
    persona_instance_id: str,
    parent_instance_ids: list[str],
    *,
    goal_id: str | None = None,
) -> PersonaInstance:
    """Declaratively REPLACE a child's steering-parent set (fan-in).

    The Launcher graph-save reconciler asserts the desired set per child
    with this; it is idempotent (re-asserting the same set is a no-op) and
    the single write path for the persisted living-graph wiring. An empty
    set detaches the child (standalone owner).
    """
    normalized = dedupe_tokens(parent_instance_ids)
    if not normalized:
        return store.detach_parents(persona_instance_id)
    return store._apply_steer_edges(persona_instance_id, normalized, goal_id=goal_id)


def add_parent(
    store: PersonaInstanceStore,
    persona_instance_id: str,
    parent_instance_id: str,
    *,
    goal_id: str | None = None,
) -> PersonaInstance:
    """Idempotently ADD one parent to a child's steering set (set-union)."""
    normalized_parent = safe_optional_token(parent_instance_id)
    if not normalized_parent:
        raise ValueError("parent_instance_id is required")
    instance = store.get(persona_instance_id)
    desired = list(instance.steered_by)
    if normalized_parent not in desired:
        desired.append(normalized_parent)
    return store._apply_steer_edges(persona_instance_id, desired, goal_id=goal_id, _instance=instance)


def remove_parent(store: PersonaInstanceStore, persona_instance_id: str, parent_instance_id: str) -> PersonaInstance:
    """Remove ONE parent from a child's steering set (detach-one).

    Removing the last parent detaches the child (standalone owner).
    """
    normalized_parent = safe_optional_token(parent_instance_id)
    instance = store.get(persona_instance_id)
    desired = [pid for pid in instance.steered_by if pid != normalized_parent]
    if not desired:
        return store.detach_parents(persona_instance_id)
    return store._apply_steer_edges(persona_instance_id, desired, goal_id=instance.goal_id, _instance=instance)


def detach_parents(store: PersonaInstanceStore, persona_instance_id: str) -> PersonaInstance:
    """Clear a child's entire steering set (detach-all) → standalone owner."""
    instance = store.get(persona_instance_id)
    removed = list(instance.steered_by)
    updates: dict[str, Any] = {
        "steered_by": [],
        "spawned_by": None,
        "goal_id": None,
        "current_task_id": None,
    }
    if instance.mode == "task_bound":
        updates["mode"] = "configured"
    store._commit_steer(instance, updates, added=[], removed=removed, detached=True)
    return store.get(instance.id)


def clear_parents(store: PersonaInstanceStore, persona_instance_id: str) -> PersonaInstance:
    """Clear a child's steering set WITHOUT leaving its mission.

    The flow-doc reconcile's "drawn standalone" verb: an operator's chart
    states who steers whom — never goal membership. [detach_parents] above
    is a different statement ("leave the mission": it also strips goal_id /
    current_task_id and task-bound mode), and using it for a chart ingest
    would unbind a root agent from its live goal. Same single write path
    ([_commit_steer]) and event as every other steer mutation."""

    instance = store.get(persona_instance_id)
    removed = list(instance.steered_by)
    store._commit_steer(
        instance,
        {"steered_by": [], "spawned_by": None},
        added=[],
        removed=removed,
        detached=True,
    )
    return store.get(instance.id)


def _release_parent_references(store: PersonaInstanceStore, parent_instance_id: str) -> list[str]:
    """Transactionally release every child backlink before owner removal.

    REFUSES when any instance row will not decode, because "every" is the
    whole promise. This runs immediately before the owner's row leaves the
    live directory; a child whose file could not be read keeps a backlink to
    an id that is about to stop resolving, and nothing downstream will ever
    revisit it — the owner is gone, so no later sweep can rediscover what the
    edge pointed at. Refusing costs the operator a retire they must repair
    the store to complete; proceeding costs a dangling edge nobody can
    reconstruct.

    THE chokepoint for this fact. The one write path that removes an owner
    (:meth:`retire`, via :meth:`_archive_instance_row`) reaches it, and it
    runs BEFORE that path moves the file, so a refusal leaves the store
    exactly as it found it. It stays a chokepoint rather than an inline step
    inside that caller because the NEXT owner-removing path must arrive here
    too: the unlinking ``_delete`` that used to be the second caller was
    reaped at ML-16 with zero callers repo-wide, and whatever replaces it
    must not re-derive this rule.
    """
    scan = store.scan_all()
    if scan.unreadable:
        raise PersonaInstancesUnreadable(
            f"cannot release child backlinks for {parent_instance_id}: "
            f"{scan.unreadable} persona instance row(s) will not decode; "
            "repair or remove them before removing an owner"
        )
    released: list[str] = []
    for child in scan.instances:
        if child.id == parent_instance_id or parent_instance_id not in child.steered_by:
            continue
        kept = [parent for parent in child.steered_by if parent != parent_instance_id]
        if kept:
            store._apply_steer_edges(
                child.id,
                kept,
                goal_id=child.goal_id,
                _instance=child,
            )
        else:
            # Owner retirement changes graph topology, not the child's
            # mission membership. Preserve goal/task/mode context.
            store.clear_parents(child.id)
        released.append(child.id)
    return released


def _apply_steer_edges(
    store: PersonaInstanceStore,
    persona_instance_id: str,
    parent_instance_ids: list[str],
    *,
    goal_id: str | None,
    _instance: PersonaInstance | None = None,
) -> PersonaInstance:
    instance = _instance or store.get(persona_instance_id)
    # Resolve every parent to the id of the row actually on disk BEFORE
    # persisting, so id-scheme drift (e.g. persona_personainst_x) can never
    # enter the stored steering set. Storing a drifted parent id would make
    # the next snapshot re-emit the drift, and the Launcher graph edge (which
    # matches parents by canonical instance id) would silently fail to
    # resolve. Dedupe on the CANONICAL id so a drifted and a canonical
    # spelling of one parent collapse to a single edge. The child id is
    # already canonical here — `instance.id` is the resolved row.
    normalized: list[str] = []
    seen: set[str] = set()
    for parent in parent_instance_ids or []:
        token = safe_optional_token(parent)
        if not token:
            continue
        # Defense in depth for the steering invariant: a steering parent is a
        # persona-INSTANCE id, never a principal. Reject a non-instance-shaped
        # token loudly with the reason, BEFORE the store lookup, so no future
        # caller (a replayed spec, a mangled graph edge) can reintroduce the
        # "steered by operator" class of bug — and so the failure names the
        # category error ("not an instance id") rather than a misleading
        # "not found". Actor-token drift (persona_personainst_x) is first
        # collapsed to its canonical instance shape, which the store lookup
        # below then resolves to the real row.
        shaped = canonical_persona_instance_id(token) or token
        if not looks_like_persona_instance_id(shaped):
            raise ValueError(
                "steering parent must be a persona-instance id "
                f"({PERSONA_INSTANCE_ID_PREFIX}*), not a non-instance principal: {token!r}"
            )
        try:
            parent_instance = store.get(token)
        except Exception as exc:
            raise ValueError(f"parent persona instance not found: {token}") from exc
        canonical_parent = parent_instance.id
        if canonical_parent == instance.id:
            raise ValueError("a persona instance cannot steer itself")
        if canonical_parent in seen:
            continue
        seen.add(canonical_parent)
        store._validate_no_steering_cycle(instance.id, canonical_parent)
        normalized.append(canonical_parent)
    if not normalized:
        return store.detach_parents(instance.id)
    before = list(instance.steered_by)
    resolved_goal = safe_optional_token(goal_id) if goal_id is not None else instance.goal_id
    updates: dict[str, Any] = {
        "steered_by": normalized,
        # Denormalized legacy mirror: the primary (first) parent, for old
        # readers still keyed on the scalar. Single writer, single source.
        "spawned_by": normalized[0],
        "goal_id": resolved_goal,
    }
    if resolved_goal:
        updates["mode"] = "task_bound"
        updates["current_task_id"] = resolved_goal
    added = [pid for pid in normalized if pid not in before]
    removed = [pid for pid in before if pid not in normalized]
    store._commit_steer(instance, updates, added=added, removed=removed, detached=False)
    return store.get(instance.id)


def _commit_steer(
    store: PersonaInstanceStore,
    instance: PersonaInstance,
    updates: dict[str, Any],
    *,
    added: list[str],
    removed: list[str],
    detached: bool,
) -> None:
    changed_fields: dict[str, Any] = {}
    for attr, value in updates.items():
        if getattr(instance, attr) != value:
            setattr(instance, attr, value)
            changed_fields[attr] = value
    if not changed_fields:
        return
    instance.updated_at = now()
    store._write(instance)
    store._event(
        "persona_instance.steered",
        instance,
        {
            "goal_id": instance.goal_id,
            "spawned_by": instance.spawned_by,
            "steered_by": list(instance.steered_by),
            "added": added,
            "removed": removed,
            "detached": bool(detached),
        },
    )
    # S6 producer: the flagship field-patch case. ``changed_fields`` is the
    # exact set this steer mutation wrote (steered_by/spawned_by, plus
    # goal_id/mode/current_task_id when the re-route changed them). Live
    # unless read_model.delta_patches is explicitly off (it ships on).
    store._emit_state_patch(instance, changed_fields)


def _validate_no_steering_cycle(store: PersonaInstanceStore, persona_instance_id: str, parent_instance_id: str) -> None:
    # Multi-parent DAG walk: adding parent → child must not let the child
    # reach itself through the steering graph. We only reject when the child
    # is reachable from the new parent (a real cycle); a diamond (two parents
    # sharing an ancestor) is fine, so we track a visited set separately from
    # the cycle test rather than raising on any re-visit.
    #
    # The walk ADMITS the edge by exhausting the frontier without finding
    # the child, so every node it fails to open is a subgraph it silently
    # declares cycle-free. A row that will not decode therefore hides any
    # cycle BEHIND it and the edge is admitted into a graph that now has one.
    # An ABSENT ancestor is not that condition: ``get`` re-raises
    # ``FileNotFoundError`` for an id with no row, which is a dangling
    # reference the steering repair exists to strip, and it really does end
    # the walk — nothing is reachable through a node that is not there. A row
    # that EXISTS and will not decode is the unknowable case, and it refuses.
    visited: set[str] = set()
    unreadable = 0
    frontier = dedupe_tokens([parent_instance_id])
    while frontier:
        cursor = frontier.pop()
        if cursor == persona_instance_id:
            raise ValueError("steering edge would create a cycle")
        if cursor in visited:
            continue
        visited.add(cursor)
        try:
            parent = store.get(cursor)
        except FileNotFoundError:
            continue
        except Exception:
            unreadable += 1
            continue
        frontier.extend(dedupe_tokens(list(parent.steered_by)))
    if unreadable:
        raise PersonaInstancesUnreadable(
            f"cannot prove the steering edge {parent_instance_id} -> {persona_instance_id} "
            f"is acyclic: {unreadable} ancestor row(s) will not decode; "
            "repair or remove them before steering"
        )
