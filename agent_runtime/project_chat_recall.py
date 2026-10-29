"""Recall across the agent's own store and its Projects' shared chat stores (H-P7, plan §6).

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §6. An agent
searches a Project's shared store (``project_chat_fold``) beside its own ``state.db`` only when BOTH
switches are on: the instance's ``recall_shared_projects`` (default off;
``runtime.persona.instance.recall.set``) and the Project's ``chats`` share. Every shared store is
opened READ-ONLY here; the fold is its only writer, and memory extraction (``agent/background_review``)
reads the live turn, never a store.

* :func:`shared_stores_for` resolves the stores for an instance; :func:`shared_stores_for_current_turn`
  reads the instance from the turn's ``launcher_invocation``, so ``session_search`` needs no new
  argument from upstream's tool wiring.
* :func:`merge_discover` runs ``_discover`` in each shared store (the own store's exclusions —
  ``current_lineage``, hidden sources — do not apply there) and merges by PER-STORE rank, round-robin,
  own store first: FTS5 BM25 scores are not comparable across databases. Every shared hit carries
  ``shared_from {project, project_id, author, machine}`` and the link ``@project:<id>/<session>``.
* :func:`recall_session_search` is the whole recall: upstream's PUBLIC ``session_search`` against the
  own store, the same call against each enabled shared store (no current session there), the merge,
  and an ``@project:<id>/<session>`` link resolved (read or scroll) against that store read-only —
  refused when the store is not enabled for this agent. It replaces nothing yet: the agent's tool
  call still reaches upstream's ``session_search`` directly, and routing it here is one edit in an
  upstream file the footprint ratchet holds (row RT-PROJECT-CHAT-RECALL-ACROSS-STORES, owner decision).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

__layer__ = "stores"

PROJECT_LINK_PREFIXES = ("@project:", "project:")


@dataclass
class SharedStore:
    project_id: str
    name: str
    db: Any


def shared_stores_for(persona_instance_id: str | None) -> list[SharedStore]:
    """The shared stores this instance may recall from (empty unless both switches are on)."""

    if not persona_instance_id:
        return []
    from .errors import NotFound
    from .persona_assignments import PersonaInstanceStore
    from .project_chat_fold import open_shared_store
    from .project_store import category, load_project
    from .store import WorkspaceStore

    try:
        instance = PersonaInstanceStore().get(persona_instance_id)
    except (FileNotFoundError, KeyError, NotFound):
        return []
    if not getattr(instance, "recall_shared_projects", False) or not instance.workspace_id:
        return []
    try:
        held = WorkspaceStore().get(instance.workspace_id).project_ids
    except NotFound:
        return []
    stores = []
    for project_id in held:
        record = load_project(project_id)
        if not category(record, "chats").get("shared"):
            continue
        db = open_shared_store(project_id, read_only=True)
        if db is not None:
            stores.append(SharedStore(project_id, str(record.get("name") or project_id), db))
    return stores


def shared_stores_for_current_turn() -> list[SharedStore]:
    from .launcher_invocation import current_invocation

    return shared_stores_for((current_invocation() or {}).get("persona_instance_id"))


def _author_label(db: Any, session_id: str) -> tuple[str | None, str | None]:
    session = db.get_session(session_id) or {}
    config = session.get("model_config") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except ValueError:
            config = {}
    instance_id = (config or {}).get("persona_instance_id")
    author = None
    if instance_id:
        from .persona_assignments import PersonaInstanceStore

        try:
            author = PersonaInstanceStore().get(instance_id).display_name
        except Exception:  # a teammate's instance this machine never minted: name it by id
            author = instance_id
    return author, (config or {}).get("shared_from_machine")


def _labelled(entry: dict[str, Any], store: SharedStore) -> dict[str, Any]:
    author, machine = _author_label(store.db, entry["session_id"])
    entry = {**entry, "link": f"@project:{store.project_id}/{entry['session_id']}",
             "shared_from": {"project": store.name, "project_id": store.project_id, "author": author,
                             "machine": machine}}
    label = f"— {author or 'a teammate'}'s agent" + (f", on {machine}" if machine else "")
    entry["shared_label"] = label
    return entry


def merge_discover(own_payload: str, stores: list[SharedStore], *, discover, limit: int) -> str:
    """The own discover payload with every shared store's hits merged in by per-store rank (own first).

    ``discover(db)`` answers the same query against one shared store, with no current-lineage exclusion.
    """

    own = json.loads(own_payload)
    if not stores or not own.get("success", True) or own.get("mode") != "discover":
        return own_payload
    ranked: list[list[dict[str, Any]]] = [list(own.get("results") or [])]
    for store in stores:
        payload = json.loads(discover(store.db))
        ranked.append([_labelled(entry, store) for entry in payload.get("results") or []])
    merged: list[dict[str, Any]] = []
    for rank in range(max(len(r) for r in ranked)):
        for results in ranked:  # round-robin, own store first on every tie of rank
            if rank < len(results):
                merged.append(results[rank])
    merged = merged[: max(limit, len(ranked[0]))]
    return json.dumps({**own, "results": merged, "count": len(merged),
                       "shared_stores_searched": [store.project_id for store in stores]}, ensure_ascii=False)


def project_link(session_id: Any) -> tuple[str, str] | None:
    """``(project_id, session_id)`` of an ``@project:<id>/<session>`` link, else None."""

    if not isinstance(session_id, str):
        return None
    for prefix in PROJECT_LINK_PREFIXES:
        if session_id.startswith(prefix):
            project_id, _, session = session_id[len(prefix):].partition("/")
            return (project_id, session) if project_id and session else None
    return None


def store_for_link(project_id: str, stores: list[SharedStore]) -> SharedStore | None:
    return next((store for store in stores if store.project_id == project_id), None)


def close_stores(stores: list[SharedStore]) -> None:
    for store in stores:
        try:
            store.db.close()
        except Exception:  # a read-only handle that fails to close leaks nothing durable
            pass


def recall_session_search(*, shared_stores: list[SharedStore] | None = None, **kwargs: Any) -> str:
    """``tools.session_search_tool.session_search(**kwargs)`` plus the agent's enabled shared stores.

    ``shared_stores`` None = the current turn's (empty unless the agent enabled recall across
    Projects). Another profile's store (``profile=``) is never mixed with a Project's.
    """

    from tools.session_search_tool import session_search
    from tools.registry import tool_error

    if str(kwargs.get("profile") or "").strip():
        return session_search(**kwargs)
    stores = shared_stores_for_current_turn() if shared_stores is None else shared_stores
    try:
        link = project_link(kwargs.get("session_id"))
        if link:
            store = store_for_link(link[0], stores)
            if store is None:
                return tool_error(f"@project:{link[0]} is not a shared chat store this agent recalls from",
                                  success=False)
            return session_search(**{**kwargs, "db": store.db, "current_session_id": None, "session_id": link[1]})
        result = session_search(**kwargs)
        session_id = kwargs.get("session_id")
        if stores and not (isinstance(session_id, str) and session_id.strip()):
            limit = max(1, min(10, int(kwargs.get("limit") or 3)))
            shared_kwargs = {**kwargs, "limit": limit, "current_session_id": None, "exclude_session_ids": None}
            result = merge_discover(result, stores, limit=limit,
                                    discover=lambda db: session_search(**{**shared_kwargs, "db": db}))
        return result
    finally:
        if shared_stores is None:
            close_stores(stores)
