"""Recall across the agent's own store and its workspace's shared chat store (H-P7, plan §6).

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §6, re-homed on the
workspace (RT-WS-ABSORB-RETIRE-PROJECT). An agent searches its workspace's shared store
(``workspace_chat_fold``) beside its own ``state.db`` only when BOTH switches are on: the instance's
``recall_shared_projects`` (default off; ``runtime.persona.instance.recall.set``) and the workspace's
``chats`` share. The shared store is opened READ-ONLY here; the fold is its only writer, and memory
extraction (``agent/background_review``) reads the live turn, never a store. (The module and the
instance field keep their Project-edition names until RT-WS-ABSORB-CHAT-NAMES-RESIDUE.)

* :func:`shared_stores_for` resolves the store for an instance; :func:`shared_stores_for_current_turn`
  reads the instance from the turn's ``launcher_invocation``, so ``session_search`` needs no new
  argument from upstream's tool wiring.
* :func:`merge_discover` runs ``_discover`` in the shared store (the own store's exclusions —
  ``current_lineage``, hidden sources — do not apply there) and merges by PER-STORE rank, round-robin,
  own store first: FTS5 BM25 scores are not comparable across databases. Every shared hit carries
  ``shared_from {workspace, workspace_id, author, machine}`` and the link ``@workspace:<id>/<session>``.
* :func:`recall_session_search` is the whole recall: upstream's PUBLIC ``session_search`` against the
  own store, the same call against the enabled shared store (no current session there), the merge,
  and an ``@workspace:<id>/<session>`` link resolved (read or scroll) against that store read-only —
  refused when the store is not enabled for this agent.
* :func:`route_registered_handler` is the agent's door: the append-only seam at the end of
  ``tools/session_search_tool.py`` (owner ruling 2026-10-29, row RT-PROJECT-CHAT-RECALL-ACROSS-STORES)
  wraps the registered handler, so the tool call recalls across the enabled store while every
  direct caller of upstream's ``session_search`` keeps upstream's single-store behaviour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

__layer__ = "stores"

SHARED_LINK_PREFIXES = ("@workspace:", "workspace:")


@dataclass
class SharedStore:
    workspace_id: str
    name: str
    db: Any


def shared_stores_for(persona_instance_id: str | None) -> list[SharedStore]:
    """The shared store this instance may recall from: its workspace's, when both switches are on."""

    if not persona_instance_id:
        return []
    from .errors import NotFound
    from .persona_assignments import PersonaInstanceStore
    from .workspace_chat_export import ChatHome
    from .workspace_chat_fold import open_shared_store
    from .store import WorkspaceStore
    from .workspace_categories import category
    from .workspace_slots import load_document

    try:
        instance = PersonaInstanceStore().get(persona_instance_id)
    except (FileNotFoundError, KeyError, NotFound):
        return []
    workspace_id = instance.workspace_id
    if not getattr(instance, "recall_shared_projects", False) or not workspace_id:
        return []
    if not category(load_document(workspace_id), "chats").get("shared"):
        return []
    db = open_shared_store(ChatHome(workspace_id), read_only=True)
    if db is None:
        return []
    try:
        name = WorkspaceStore().get(workspace_id).name or workspace_id
    except NotFound:
        name = workspace_id
    return [SharedStore(workspace_id, str(name), db)]


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
    entry = {**entry, "link": f"@workspace:{store.workspace_id}/{entry['session_id']}",
             "shared_from": {"workspace": store.name, "workspace_id": store.workspace_id, "author": author,
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
                       "shared_stores_searched": [store.workspace_id for store in stores]}, ensure_ascii=False)


def shared_link(session_id: Any) -> tuple[str, str] | None:
    """``(workspace_id, session_id)`` of an ``@workspace:<id>/<session>`` link, else None."""

    if not isinstance(session_id, str):
        return None
    for prefix in SHARED_LINK_PREFIXES:
        if session_id.startswith(prefix):
            workspace_id, _, session = session_id[len(prefix):].partition("/")
            return (workspace_id, session) if workspace_id and session else None
    return None


def store_for_link(workspace_id: str, stores: list[SharedStore]) -> SharedStore | None:
    return next((store for store in stores if store.workspace_id == workspace_id), None)


def close_stores(stores: list[SharedStore]) -> None:
    for store in stores:
        try:
            store.db.close()
        except Exception:  # a read-only handle that fails to close leaks nothing durable
            pass


def _recall(search, *, profile: Any, session_id: Any, limit: Any,
            shared_stores: list[SharedStore] | None) -> str:
    """The recall, over ``search(**overrides)`` — one upstream ``session_search`` call with these overrides."""

    from tools.registry import tool_error

    if str(profile or "").strip():
        return search()
    stores = shared_stores_for_current_turn() if shared_stores is None else shared_stores
    try:
        link = shared_link(session_id)
        if link:
            store = store_for_link(link[0], stores)
            if store is None:
                return tool_error(f"@workspace:{link[0]} is not a shared chat store this agent recalls from",
                                  success=False)
            return search(db=store.db, current_session_id=None, session_id=link[1])
        result = search()
        if stores and not (isinstance(session_id, str) and session_id.strip()):
            limit = max(1, min(10, int(limit or 3)))
            result = merge_discover(result, stores, limit=limit, discover=lambda db: search(
                db=db, limit=limit, current_session_id=None, exclude_session_ids=None))
        return result
    finally:
        if shared_stores is None:
            close_stores(stores)


def recall_session_search(*, shared_stores: list[SharedStore] | None = None, **kwargs: Any) -> str:
    """``tools.session_search_tool.session_search(**kwargs)`` plus the agent's enabled shared stores.

    ``shared_stores`` None = the current turn's (empty unless the agent enabled recall across its
    workspace's shared chats). Another profile's store (``profile=``) is never mixed with a workspace's.
    """

    from tools.session_search_tool import session_search

    return _recall(lambda **overrides: session_search(**{**kwargs, **overrides}),
                   profile=kwargs.get("profile"), session_id=kwargs.get("session_id"),
                   limit=kwargs.get("limit"), shared_stores=shared_stores)


_ROUTED = "_project_chat_recall_routed"


def routed_handler(handler: Any) -> Any:
    """The registered ``session_search`` handler, recalling across the turn's enabled shared stores."""

    if getattr(handler, _ROUTED, False):
        return handler

    def routed(args: dict[str, Any], **kw: Any) -> str:
        args = dict(args or {})

        def search(**overrides: Any) -> str:
            call_kw = {**kw, **{key: overrides.pop(key) for key in ("db", "current_session_id") if key in overrides}}
            return handler({**args, **overrides}, **call_kw)

        return _recall(search, profile=args.get("profile"), session_id=args.get("session_id"),
                       limit=args.get("limit"), shared_stores=None)

    setattr(routed, _ROUTED, True)
    return routed


def route_registered_handler(registry: Any) -> None:
    """Called once by the seam in ``tools/session_search_tool.py`` right after upstream registers the tool."""

    entry = registry.get_entry("session_search", scope=None)
    if entry is not None:
        entry.handler = routed_handler(entry.handler)
