"""The store's floor: the model files (read / write / list — ``_write_model`` is
the ONE model writer), the slug and display-name bounds, the active-pointer
compare-and-set with its paired scope patch, and the three thin stores over the
files (``AgentStore``, ``RunStore``, ``IncidentStore``) with ``ACTIVE_RUN_STATES``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TypeVar

from hermes_time import now
from utils import atomic_json_write

from .. import paths
from ..errors import NotFound
from ..events import EventLog
from ..models import AgentPersona, AgentRun, Incident
from ..serde import from_jsonable, read_json, safe_id, to_jsonable
from ..states import RunState
from ..store_events import emit_store_event

__layer__ = "stores"


T = TypeVar("T")

ACTIVE_RUN_STATES = frozenset({RunState.QUEUED, RunState.STARTING, RunState.RUNNING, RunState.WAITING_ON_TOOL, RunState.WAITING_ON_APPROVAL})


def _safe_display_name(value) -> str:
    return " ".join(str(value or "").split())[:160]


def _slugify(value) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:80] or "item"


def _dedupe_ids(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = safe_id(value)
        if clean and clean not in result:
            result.append(clean)
    return result


def read_model_json(path: Path) -> dict:
    """``serde.read_json`` with the store's missing-file contract: a model file
    that is not there is :class:`~agent_runtime.errors.NotFound`, the exception
    every store caller already catches."""

    try:
        return read_json(path)
    except FileNotFoundError:
        raise NotFound(str(path)) from None


def read_pointer(path: Path, key: str) -> str | None:
    """One active pointer (``key`` of the pointer file at ``path``), or ``None``
    when the file is missing or unreadable — the read ``active_id()`` performs,
    shared so a store write never has to construct a store to re-read one."""

    try:
        raw = read_model_json(path)
    except Exception:
        return None
    return safe_id(raw.get(key))


def _read_model(cls: type[T], path: Path) -> T:
    return from_jsonable(cls, read_model_json(path))


def _write_model(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, to_jsonable(model), indent=2, sort_keys=True)


def _emit_active_scope_patch(event_log: EventLog) -> None:
    """Append the ``scope`` ``state.patched`` row beside an activation event.

    WS1 (instant-workspace-switching plan §1.1). Both ``set_active`` writes call
    this from inside the write, immediately after the pointer file lands and
    before the paired ``workspace.activated`` / ``realm.activated`` domain event —
    same chokepoint, same drain, so the two coalesce into ONE batch and the event
    free-rides on this row's fold gate instead of demoting the batch to a full
    O(world) core.

    **Both pointers are re-read from disk** (:func:`read_pointer`, the read
    ``active_id()`` performs — no store is constructed inside a store write),
    not taken from the caller's
    local variable, and that is deliberate: a realm activate can re-park the
    workspace through a second write, and the patch's contract is that it carries
    the pair as it stands ON DISK when the event is appended. Reading is two small
    JSON files that the write path has just touched.

    Best effort, exactly like ``store_events.emit_store_event`` — a broken
    event log must not fail an activation. The empty-frame hazard a silent skip
    would otherwise open (the covered domain event riding alone and shipping a
    patch frame with no rows) is closed one level up by
    ``stream.batch_carries_patch_rows``, which demotes a batch carrying no
    ``state.patched`` at all; this function does not have to hold that invariant
    by itself.

    The function-local import mirrors every other ``state_patches`` reach in the
    store layer: this module is imported very early and ``state_patches`` pulls
    the config graph.
    """

    try:
        from ..state_patches.emit import emit_scope_patch

        emit_scope_patch(
            event_log,
            active_workspace_id=read_pointer(paths.active_workspace_path(), "workspace_id"),
            active_realm_id=read_pointer(paths.active_realm_path(), "realm_id"),
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "active-scope patch emit failed", exc_info=True
        )


def _parse_intent_basis(value):
    """Parse an ISO-8601 UTC intent basis into a datetime; None when absent or
    unparseable (fail-open — a malformed basis must never block a scope
    switch, it just loses supersede protection for that one write)."""
    if not value:
        return None
    try:
        from datetime import datetime

        text = str(value).strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


#: The three answers of the active-pointer compare-and-set. Plain constants, not
#: an Enum: the words ride the RPC result as ``reason`` and are spelled by
#: ``scope_activation`` and the launcher (fork-hygiene row 2026-09-25).
ACTIVATION_APPLY = "apply"
ACTIVATION_SUPERSEDED = "superseded"
ACTIVATION_DUPLICATE = "duplicate"


def _resolve_activation_write(pointer_path: Path, key: str, value: str | None, issued_at: str | None) -> tuple[str, str | None, str]:
    """Compare-and-set decision for an active-pointer write.

    Mutation intents carry the wall-clock instant the operator issued them
    (``issued_at``). Transport can deliver an intent twice (serve timeout →
    CLI fallback re-runs the same argv) or late (a wedged serve child drains
    an abandoned request minutes later) — the intent's basis, not its arrival
    order, decides who wins. Returns ``(decision, current_value, basis)``:

    - ``apply``      — write the pointer and emit the activation event.
    - ``superseded`` — a strictly newer intent already owns the pointer; do
      not write, do not emit.
    - ``duplicate``  — the exact same intent (same basis, same target) was
      already applied; do not write, do not emit (exact-once event feed).

    A caller with no basis (human at a terminal, legacy callers) is stamped
    ``now()`` so the basis timeline always advances and manual actions win.
    """
    basis = issued_at or now()
    try:
        current = read_model_json(pointer_path)
    except Exception:
        return ACTIVATION_APPLY, None, basis
    current_value = safe_id(current.get(key))
    incoming = _parse_intent_basis(basis)
    stored = _parse_intent_basis(current.get("intent_issued_at"))
    if incoming is None or stored is None:
        return ACTIVATION_APPLY, current_value, basis
    if incoming < stored:
        return ACTIVATION_SUPERSEDED, current_value, basis
    if incoming == stored and value == current_value:
        return ACTIVATION_DUPLICATE, current_value, basis
    return ACTIVATION_APPLY, current_value, basis


def apply_activation(
    pointer_path: Path,
    key: str,
    value: str | None,
    issued_at: str | None,
    *,
    name: str | None,
    event_type: str,
    event_log: EventLog,
) -> dict:
    """The ONE active-pointer write (``WorkspaceStore.set_active`` and
    ``RealmStore.set_active`` are this with their key, path and event).

    Refused intents (:data:`ACTIVATION_SUPERSEDED` / :data:`ACTIVATION_DUPLICATE`)
    write nothing and emit nothing, and answer the pointer as it stands. An
    applied one writes the pointer with its basis, then the scope patch, then
    the ``<kind>.activated`` event — WS1: the patch FIRST, so an activate event
    in the log is always preceded by the row that expresses it, and both
    pointers ride every row, so a realm activate that also re-parks the
    workspace can never ship half a pair.
    """

    decision, current_value, basis = _resolve_activation_write(pointer_path, key, value, issued_at)
    if decision != ACTIVATION_APPLY:
        return {key: current_value, "applied": False, "reason": decision, f"requested_{key}": value}
    _write_model(pointer_path, {key: value, "updated_at": now(), "intent_issued_at": basis})
    _emit_active_scope_patch(event_log)
    payload = {key: value, "name": name} if value else {"cleared": True}
    emit_store_event(event_log, event_type, payload, domain="store")
    return {key: value, "applied": True}


def _list_models(cls: type[T], directory: Path) -> list[T]:
    if not directory.exists():
        return []
    items: list[T] = []
    for path in directory.glob("*.json"):
        try:
            items.append(_read_model(cls, path))
        except NotFound:
            # Archive moves are evidence-preserving but not invisible to UI polls:
            # a file can disappear after glob() and before read_text().
            continue
    return sorted(items, key=lambda item: item.id)


class AgentStore:
    def __init__(self, event_log: EventLog | None = None):
        self.event_log = event_log or EventLog()

    def save(self, persona: AgentPersona) -> AgentPersona:
        _write_model(paths.agent_path(persona.id), persona)
        emit_store_event(
            self.event_log,
            "persona.updated",
            {"persona_id": persona.id, "display_name": persona.display_name},
            domain="store",
        )
        return persona

    def get(self, persona_id: str) -> AgentPersona:
        return _read_model(AgentPersona, paths.agent_path(persona_id))

    def list_all(self) -> list[AgentPersona]:
        return _list_models(AgentPersona, paths.agents_dir())


class RunStore:
    def get(self, run_id: str) -> AgentRun:
        return _read_model(AgentRun, paths.run_path(run_id))

    def list_all(self) -> list[AgentRun]:
        return _list_models(AgentRun, paths.runs_dir())


class IncidentStore:
    def get(self, incident_id: str) -> Incident:
        return _read_model(Incident, paths.incident_path(incident_id))

    def list_all(self) -> list[Incident]:
        return _list_models(Incident, paths.incidents_dir())
