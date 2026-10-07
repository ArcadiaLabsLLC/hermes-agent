"""``runtime.realm.*`` answers off the serve reader loop (lane h-newchat-t1).

Live 2026-10-06 01:25 (local): the launcher's periodic ``runtime.realm.sync.status`` ran
INLINE on the dispatcher -- a remote fetch at 01:25:01.0, the drift walk until the
sidecar at 01:25:04.18 -- and the operator's first chat send, dispatched at 01:25:01.75,
was accepted only after it (chat-turn lock 01:25:04.23, ``send_to_admit_ms=2564`` against
100-260 ms on every other turn). The verbs now hand their answer to ``spawn_reply`` and
run one at a time among themselves.
"""

from __future__ import annotations

import threading

from agent_runtime import realm_verbs, serve_rpc
from agent_runtime.serve_rpc.protocol import RpcContext, is_deferred


def _status_request(rid: str = "rs") -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": "runtime.realm.sync.status",
            "params": {"realm_id": "realm_x"}}


def test_a_realm_status_never_holds_the_reader_loop(monkeypatch):
    """The dispatcher returns before the verb runs; the worker writes the answer.

    *Killing mutation:* answer inline (``return build()`` without offering it to
    ``spawn_reply``) -- the dispatcher blocks on the verb and the gate below never opens.
    """

    entered = threading.Event()
    release = threading.Event()

    def _slow_status(realm_id, *, credential=None):
        entered.set()
        assert release.wait(5), "the verb was never released"
        return {"id": realm_id, "state": "clean"}

    monkeypatch.setattr(realm_verbs, "realm_sync_status", _slow_status)
    handed: list = []
    pool = []

    def _spawn_reply(build):
        handed.append(build)
        worker = threading.Thread(target=lambda: handed.append(build()), daemon=True)
        pool.append(worker)
        worker.start()
        return True

    dispatcher_done = threading.Event()
    frames: list = []

    def _dispatch():
        frames.append(serve_rpc.handle_request(_status_request(), RpcContext(spawn_reply=_spawn_reply)))
        dispatcher_done.set()

    threading.Thread(target=_dispatch, daemon=True).start()
    assert entered.wait(5), "the verb never ran"
    assert dispatcher_done.wait(2), "the dispatcher waited for the realm verb"
    assert is_deferred(frames[0])
    release.set()
    pool[0].join(5)
    reply = handed[-1]
    assert reply["id"] == "rs" and reply["result"] == {"id": "realm_x", "state": "clean"}


def test_without_a_worker_lane_the_verb_still_answers_inline(monkeypatch):
    monkeypatch.setattr(realm_verbs, "realm_sync_status",
                        lambda realm_id, *, credential=None: {"id": realm_id})
    frame = serve_rpc.handle_request(_status_request("inline"))
    assert frame["result"] == {"id": "realm_x"}


def test_two_deferred_realm_verbs_never_run_at_once(monkeypatch):
    """The inline lane serialized realm verbs for free; the worker lane keeps that."""

    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def _status(realm_id, *, credential=None):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        threading.Event().wait(0.05)
        with lock:
            live["now"] -= 1
        return {"id": realm_id}

    monkeypatch.setattr(realm_verbs, "realm_sync_status", _status)
    workers = []

    def _spawn_reply(build):
        worker = threading.Thread(target=build, daemon=True)
        workers.append(worker)
        worker.start()
        return True

    for rid in ("a", "b", "c"):
        assert is_deferred(serve_rpc.handle_request(_status_request(rid), RpcContext(spawn_reply=_spawn_reply)))
    for worker in workers:
        worker.join(5)
    assert live["peak"] == 1
