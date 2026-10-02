"""Instance chat directories use SessionDB's existing cwd, not a side store."""
from __future__ import annotations

from pathlib import Path
from contextlib import closing

from . import paths
from .conversation_owner import session_client_scope

__layer__ = "stores"


def initialize_conversation_workspace(db, session_id: str, *, directory: str | None) -> None:
    row = db.get_session(session_id)
    if session_client_scope(row) is None or row.get("cwd"):
        return
    selected = Path(directory) if directory else (
        paths.store_root() / "conversation-workspaces" / session_id)
    if not directory:
        selected.mkdir(parents=True, exist_ok=True)
    db.update_session_cwd(session_id, str(selected.resolve()))


def conversation_workspace(row: dict) -> dict | None:
    value = row.get("cwd")
    if not isinstance(value, str) or not value:
        return None
    directory = Path(value)
    return {"id": row["id"], "path": value,
            "name": "Conversation files" if directory.parent == paths.store_root() / "conversation-workspaces"
            else directory.name or value}


def pinned_conversation_workdir(db, session_id: str | None) -> str | None:
    if not session_id:
        return None
    if db is None:
        from .chat_session_scope import open_chat_session_db, resolve_chat_session_scope, SessionDbAccess

        scope = resolve_chat_session_scope(session_id=session_id)
        if scope.mismatch is not None:
            raise ValueError("The conversation workspace could not be verified.")
        opened = open_chat_session_db(scope, access=SessionDbAccess.READ)
        if opened is None:
            if scope.db_path.exists():
                raise ValueError("The conversation workspace could not be verified.")
            return None
        with closing(opened):
            return pinned_conversation_workdir(opened, session_id)
    row = db.get_session(session_id)
    if row is None or session_client_scope(row) is None:
        return None
    value = row.get("cwd")
    if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_dir():
        raise ValueError("The conversation workspace is unavailable. Restore it before continuing.")
    return value
