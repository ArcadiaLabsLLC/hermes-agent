"""Idempotent receipts for native child commands, never child execution state.

Live-child receipts are not evicted: pressure refuses new commands rather than
forgetting a request that could still be executed twice. Once a child has finished,
receipts older than ten minutes expire; its old reference cannot execute work.
"""
import hashlib
import hmac
import json
import threading
import time
import weakref
from dataclasses import dataclass

from agent_runtime import _upstream_doors as upstream
from .model import Refusal, SubagentError
from .references import references

__layer__ = "lanes"


@dataclass
class _Receipt:
    fingerprint: str
    data: dict
    agent: object
    started_at: object
    recorded_at: float
    completion: object


class CommandReceipts:
    def __init__(self, limit=1024):
        self.limit = limit
        self._lock = threading.Lock()
        self._rows = {}

    def _prune(self):
        records, lock = upstream.subagent_registry()
        with lock:
            live = {(id(r.get("agent")), r.get("started_at")) for r in records.values()}
        now = time.monotonic()
        for key, row in list(self._rows.items()):
            if (id(row.agent()), row.started_at) not in live and now - row.recorded_at > 600:
                del self._rows[key]

    def read(self, generation, params):
        with self._lock:
            self._prune()
            row = self._rows.get((generation, params["request_id"]))
            if row is None:
                return {"request_id": params["request_id"], "child_ref": params["child_ref"],
                        "subagent_id": None, "operation": None, "status": "unknown", "missed_steer": None}
            if not hmac.compare_digest(row.data["child_ref"], params["child_ref"]):
                raise SubagentError(Refusal.STALE)
            data = dict(row.data)
            completion = row.completion
        if data["operation"] == "steer" and completion is not None:
            from .completion import missed_steering
            data["missed_steer"] = missed_steering(completion)
        return data

    def execute(self, operation, params, generation, resolve, authorize):
        fingerprint = hashlib.sha256(json.dumps(
            [operation, params["child_ref"], params.get("text")], ensure_ascii=True).encode()).hexdigest()
        key = (generation, params["request_id"])
        with self._lock:
            self._prune()
            if previous := self._rows.get(key):
                if not hmac.compare_digest(previous.fingerprint, fingerprint):
                    raise SubagentError(Refusal.INVALID)
                return dict(previous.data)
            if len(self._rows) >= self.limit:
                raise SubagentError(Refusal.UNAVAILABLE)
            record = resolve()
            from .completion import completion_locator
            data = {"request_id": params["request_id"], "child_ref": params["child_ref"],
                    "subagent_id": record["subagent_id"], "operation": operation,
                    "status": "unknown", "missed_steer": None}
            self._rows[key] = _Receipt(fingerprint, data, weakref.ref(record["agent"]),
                record.get("started_at"), time.monotonic(), completion_locator(record))
        # Reserve before dispatch, without serializing unrelated child commands.
        # An exception can never make this ID runnable again.
        try:
            status = _apply(operation, params, record, authorize)
        except SubagentError:
            with self._lock:
                data["status"] = "refused"
            raise
        except Exception:
            status = "unknown"
        with self._lock:
            data["status"] = status
            return dict(data)


def _apply(operation, params, record, authorize):
    from tools.delegate_tool_registry import interrupt_subagent, steer_subagent

    checked = False

    def current(candidate):
        nonlocal checked
        authorize(candidate)
        checked = True
        return (candidate.get("agent") is record["agent"] and
                candidate.get("started_at") == record.get("started_at"))

    if operation == "steer":
        if not record.get("accepting_steer"):
            return "not_accepting"
        accepted = steer_subagent(record["subagent_id"], params["text"], authorize_record=current)
        return "queued" if accepted else "unknown" if checked else "not_accepting"
    accepted = interrupt_subagent(record["subagent_id"], authorize_record=current)
    return "interrupt_requested" if accepted else "unknown"


commands = CommandReceipts()


def control_records(operation, params, *, owner, records, exact, revalidate):
    generation = references.generation(owner)

    def authorize(record):
        revalidate()
        if not exact(record) or not hmac.compare_digest(references.child(owner, record), params["child_ref"]):
            raise SubagentError(Refusal.STALE)

    def resolve():
        for record in records:
            if exact(record) and hmac.compare_digest(references.child(owner, record), params["child_ref"]):
                return record
        raise SubagentError(Refusal.STALE)

    revalidate()
    if operation == "receipt":
        return commands.read(generation, params)
    return commands.execute(operation, params, generation, resolve, authorize)
