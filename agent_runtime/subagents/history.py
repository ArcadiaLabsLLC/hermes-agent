"""One owned read projection for native/operator persisted child observations."""
import hmac
import sqlite3
import time
from functools import partial

from .history_store import owned_history_sessions, read_result_history, read_saved_trees
from .model import VERSION, Refusal, SubagentError, validate_request
from .references import references

__layer__ = "lanes"


def inspect_history(operation, params, *, owner, db, session_id, home, revalidate, delegation_db_path=None):
    validate_request(operation, params)
    delegation_db_path = delegation_db_path or db.db_path
    owner = ("history", owner, str(home), str(db.db_path), str(delegation_db_path))
    generation = references.require_generation(owner, params.get("expected_generation"))
    try:
        lineage = owned_history_sessions(db, session_id)
    except (OSError, sqlite3.Error) as exc:
        raise SubagentError(Refusal.UNAVAILABLE) from exc
    if not lineage:
        raise SubagentError(Refusal.UNAVAILABLE)
    projections, sources, truncated = {}, {}, False
    readers = {"result": partial(read_result_history, db.db_path, delegation_db_path, lineage),
               "tree": partial(read_saved_trees, home, lineage)}
    for kind in readers if operation == "history" else (operation,):
        try:
            projections[kind], bounded = readers[kind]()
            sources[kind] = True
            truncated |= bounded
        except (OSError, sqlite3.Error, SubagentError) as exc:
            if operation != "history":
                raise SubagentError(Refusal.UNAVAILABLE) from exc
            projections[kind], sources[kind] = [], False
    if operation == "history":
        results, trees = projections["result"], projections["tree"]
        data = {"results": [{**{key: value for key, value in result.items() if key in
                   ("goal", "status", "model", "task_index", "completed_at", "exit_reason", "source")},
                   "history_ref": references.historical(owner, "result", key, result)} for key, result in results],
                "trees": [{**{key: value for key, value in tree.items() if key in ("label", "started_at", "finished_at")},
                           "count": len(tree["children"]), "history_ref": references.historical(owner, "tree", key, tree)}
                          for key, tree in trees],
                "truncated": truncated, "results_available": sources["result"], "trees_available": sources["tree"]}
    else:
        found = next((value for key, value in projections[operation] if hmac.compare_digest(
            references.historical(owner, operation, key, value), params["history_ref"])), None)
        if found is None:
            raise SubagentError(Refusal.STALE)
        data = {"history_ref": params["history_ref"], operation: found}
    revalidate()
    return {"version": VERSION, "generation": generation, "observed_at": time.time(), **data}
