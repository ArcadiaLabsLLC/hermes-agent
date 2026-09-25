"""The store's floor: the model files (read / write / list — ``_write_model`` is
the ONE model writer), the slug and display-name bounds, the active-pointer
compare-and-set with its paired scope patch, and the three thin stores over the
files (``AgentStore``, ``RunStore``, ``IncidentStore``) with ``ACTIVE_RUN_STATES``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TypeVar

from hermes_time import now
from utils import atomic_json_write

from .. import paths
from ..errors import NotFound
from ..events import EventLog
from ..models import AgentPersona, AgentRun, Event, Incident
from ..serde import from_jsonable, safe_id, to_jsonable
from ..states import RunState

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


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise NotFound(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _read_model(cls: type[T], path: Path) -> T:
    return from_jsonable(cls, _read_json(path))


def _write_model(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, to_jsonable(model), indent=2, sort_keys=True)


def _append_store_event(event_log: EventLog, event_type: str, **payload) -> None:
    """Advance the EventLog watermark after a store mutation (Stage 12).

    The stream/read-model pipeline is watermark-gated: a store write with no
    event is invisible to every consumer (launcher snapshot, serve read model)
    until an unrelated event advances the offset. Emission lives HERE, at the
    store chokepoint, so programmatic callers are covered — not just CLI verbs.
    Payload values of None are dropped. Best effort: a broken event log must
    not fail the write, but the failure is logged, never silent.
    """
    try:
        body = {key: value for key, value in payload.items() if value is not None}
        event_log.append(Event(now(), event_type, None, None, None, body))
    except Exception:
        logging.getLogger(__name__).warning(
            "store event append failed: %s", event_type, exc_info=True
        )


def _emit_active_scope_patch(event_log: EventLog) -> None:
    """Append the ``scope`` ``state.patched`` row beside an activation event.

    WS1 (instant-workspace-switching plan §1.1). Both ``set_active`` writes call
    this from inside the write, immediately after the pointer file lands and
    before the paired ``workspace.activated`` / ``realm.activated`` domain event —
    same chokepoint, same drain, so the two coalesce into ONE batch and the event
    free-rides on this row's fold gate instead of demoting the batch to a full
    O(world) core.

    **Both pointers are re-read from the store**, not taken from the caller's
    local variable, and that is deliberate: a realm activate can re-park the
    workspace through a second write, and the patch's contract is that it carries
    the pair as it stands ON DISK when the event is appended. Reading is two small
    JSON files that the write path has just touched.

    Best effort, exactly like :func:`_append_store_event` beside it — a broken
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
        from .realms import RealmStore
        from .workspaces import WorkspaceStore

        emit_scope_patch(
            event_log,
            active_workspace_id=WorkspaceStore(event_log=event_log).active_id(),
            active_realm_id=RealmStore(event_log=event_log).active_id(),
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
        current = _read_json(pointer_path)
    except Exception:
        return "apply", None, basis
    current_value = safe_id(current.get(key))
    incoming = _parse_intent_basis(basis)
    stored = _parse_intent_basis(current.get("intent_issued_at"))
    if incoming is None or stored is None:
        return "apply", current_value, basis
    if incoming < stored:
        return "superseded", current_value, basis
    if incoming == stored and value == current_value:
        return "duplicate", current_value, basis
    return "apply", current_value, basis


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
        _append_store_event(
            self.event_log,
            "persona.updated",
            persona_id=persona.id,
            display_name=persona.display_name,
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
