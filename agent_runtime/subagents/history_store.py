"""Read existing native completion/transcript stores and saved trees, without DDL.

This is a bounded read projection, never a second writer, retention policy or
completion-delivery consumer. SessionDB supplies compression lineage.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .model import Refusal, SubagentError
from .history_projection import result_projection, tree_projection

__layer__ = "lanes"
MAX_RECORDS = 100
MAX_DOCUMENT = 2 * 1024 * 1024


def owned_history_sessions(db, session_id):
    """Compression belongs to SessionDB; delegation edges use its recorded marker.

    Branch/reset children have no matching _delegate_from and are never swept
    into another conversation's history merely because they share a parent.
    """
    owned = set(db.get_compression_lineage(session_id))
    frontier = list(owned)
    with closing(sqlite3.connect(Path(db.db_path).as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        while frontier:
            placeholders = ",".join("?" for _ in frontier)
            children = conn.execute(f"""SELECT id FROM sessions WHERE
                json_valid(model_config) AND json_extract(model_config, '$._delegate_from') IN ({placeholders})""", frontier).fetchall()
            following = set()
            for (child_id,) in children:
                following.update(db.get_compression_lineage(child_id))
            frontier = list(following - owned)
            owned.update(frontier)
            if len(owned) > 512:
                raise SubagentError(Refusal.UNAVAILABLE)
    return sorted(owned)


def history_object(raw):
    if not isinstance(raw, str) or len(raw) > MAX_DOCUMENT:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _result_entries(payload):
    entries = payload.get("results")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return [payload] if any(key in payload for key in ("summary", "error")) else []


def _read_completion_rows(conn, lineage):
    placeholders = ",".join("?" for _ in lineage)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    units = []
    if "async_delegations" in tables:
        units = conn.execute(f"""SELECT delegation_id, substr(task_json,1,{MAX_DOCUMENT + 1}),
            substr(result_json,1,{MAX_DOCUMENT + 1}), dispatched_at, completed_at, state
            FROM async_delegations WHERE (parent_session_id IN ({placeholders}) OR origin_session_id IN ({placeholders}))
            AND state NOT IN ('running','stalling','finalizing') ORDER BY completed_at DESC LIMIT ?""",
            (*lineage, *lineage, MAX_RECORDS + 1)).fetchall()
    return units


def _read_result_messages(conn, lineage):
    placeholders = ",".join("?" for _ in lineage)
    messages = conn.execute(f"""SELECT id, substr(content,1,{MAX_DOCUMENT + 1}), timestamp FROM messages
        WHERE session_id IN ({placeholders}) AND role='tool' AND tool_name='delegate_task'
        AND (active=1 OR compacted=1) ORDER BY id DESC LIMIT ?""", (*lineage, MAX_RECORDS + 1)).fetchall()
    return messages


def read_result_history(db_path, delegation_db_path, lineage):
    with closing(sqlite3.connect(Path(db_path).as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        messages = _read_result_messages(conn, lineage)
    units = []
    if Path(delegation_db_path).is_file():
        with closing(sqlite3.connect(Path(delegation_db_path).as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
            units = _read_completion_rows(conn, lineage)
    results = []
    incomplete = False
    delegation_ids = {row[0] for row in units}
    for key, task_json, result_json, started, finished, state in units:
        task = history_object(task_json)
        goals = task.get("goals")
        goals = goals if isinstance(goals, list) else [task.get("goal")]
        # Native batches retain the whole call's goals; task_index is absolute,
        # including when only a subset belongs to this async unit.
        goal_by_index = dict(enumerate(goals))
        payload = history_object(result_json)
        incomplete |= not bool(task) or not bool(payload)
        entries = _result_entries(payload) or [{"status": state}]
        for position, entry in enumerate(entries):
            index = entry.get("task_index")
            results.append((f"delegation:{key}:{position}", result_projection(entry,
                goal=goal_by_index.get(index, task.get("goal")), source="delegation", started=started, finished=finished)))
    for key, content, stamp in messages:
        payload = history_object(content)
        incomplete |= not bool(payload)
        if payload.get("delegation_id") in delegation_ids:
            continue
        for position, entry in enumerate(_result_entries(payload)):
            results.append((f"message:{key}:{position}", result_projection(entry,
                goal=entry.get("goal"), source="transcript", started=None, finished=stamp)))
    results.sort(key=lambda pair: pair[1]["completed_at"] or 0, reverse=True)
    return results[:MAX_RECORDS], incomplete or len(results) > MAX_RECORDS or len(units) > MAX_RECORDS or len(messages) > MAX_RECORDS


def read_saved_trees(home, lineage):
    root = Path(home) / "spawn-trees"
    if not root.exists():
        return [], False
    # Reject redirected roots as well as individual entries. Never trust index
    # paths or accept a path from the caller; the payload must name this owner.
    if root.resolve() != Path(home).resolve() / "spawn-trees":
        raise SubagentError(Refusal.UNAVAILABLE)
    candidates = []
    truncated = False
    scanned = 0
    for session_id in lineage:
        directory = root / ("".join(c if c.isalnum() or c in "-_" else "_" for c in session_id) or "unknown")
        if not directory.is_dir():
            continue
        if directory.resolve() != directory:
            raise SubagentError(Refusal.UNAVAILABLE)
        for path in directory.glob("*.json"):
            scanned += 1
            if scanned > 500:
                truncated = True
                break
            if path.resolve().parent != directory or path.is_symlink():
                continue
            with path.open("rb") as stream:
                raw = stream.read(MAX_DOCUMENT + 1)
            if path.resolve().parent != directory or path.is_symlink():
                continue
            if len(raw) > MAX_DOCUMENT:
                truncated = True
                continue
            payload = history_object(raw.decode("utf-8", errors="replace"))
            if payload.get("session_id") != session_id:
                continue
            if tree := tree_projection(payload):
                candidates.append((str(path.relative_to(root)), tree))
    candidates.sort(key=lambda pair: pair[1]["finished_at"] or 0, reverse=True)
    return candidates[:MAX_RECORDS], truncated or len(candidates) > MAX_RECORDS
