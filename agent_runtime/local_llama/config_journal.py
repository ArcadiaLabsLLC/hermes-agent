"""Recover config + revision publication without overwriting external edits."""
from agent_runtime.store_file_io import read_json_object
from utils import atomic_json_write
from .config import LocalLlamaError


def recover(directory, store):
    path = directory / "config-journal.json"
    if not path.exists():
        return
    row = read_json_object(path)
    current = store.read()
    if current == row.get("after"):
        revision = row["revision"]
    elif current == row.get("before"):
        revision = row["revision"] - 1
    else:
        raise LocalLlamaError("recovery_required", "Configuration changed during interrupted publication; preserve the journal for recovery", code=-32000)
    atomic_json_write(directory / "state.json", {"config_revision": revision})
    path.unlink()


def publish(directory, store, before, after, revision):
    path = directory / "config-journal.json"
    if path.exists():
        raise LocalLlamaError("recovery_required", "Resolve interrupted configuration publication first", code=-32000)
    if store.read() != before:
        raise LocalLlamaError("stale_revision", "Configuration changed outside this runtime; restart Hermes before saving", code=4090)
    atomic_json_write(path, {"before": before, "after": after, "revision": revision})
    store.write(after)
    atomic_json_write(directory / "state.json", {"config_revision": revision})
    path.unlink()
