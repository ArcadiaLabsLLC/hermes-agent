"""Only the native process boundary is doubled; service and SQLite are real."""
import os
import json
import psutil


class NativeWorker:
    def __init__(self, home, receive, lost):
        self.home, self.receive, self.lost = home, receive, lost
        self.alive = self.execution_possible = True
        self.process_identity = (os.getpid(), psutil.Process().create_time())
        self.calls, self.writes = [], []
        self.models = {}
        self.events, self.executions, self.questions, self.answers = {}, {}, {}, {}
        self.on_submit = None
        self.closed = False

    def call(self, method, params, **_):
        self.calls.append((method, params))
        sid = params.get("session_id")
        if method == "session.create":
            sid = f"native-{len(self.models)}"
            self.models[sid] = "model-a"
            self.events[sid] = []
            return {"session_id": sid, "stored_session_id": sid}
        if method == "session.resume":
            return {"session_id": sid, "stored_session_id": sid}
        if method == "session.activate":
            return {"info": {"model": self.models[sid], "provider": "local", "usage": {}}}
        if method == "model.options":
            return {"providers": [{"slug": "local", "authenticated": True,
                    "models": ["model-a", "model-b"]}]}
        if method == "config.set":
            self.models[sid] = params["value"].split()[0]
            return {}
        if method == "image.attach_bytes":
            return {"attached": True}
        if method == "prompt.submit":
            assert params["reject_if_busy"] is True
            self.executions[sid] = {"id": params["execution_id"], "status": "running",
                                    "session_key": sid, "cancel_requested": False}
            if self.on_submit:
                self.on_submit(sid)
            return {"status": "streaming"}
        if method == "session.interrupt":
            current = self.executions.get(sid)
            if current and current["id"] == params["expected_execution_id"]:
                current["cancel_requested"] = True
            return {"status": "interrupted"}
        if method == "session.events.since":
            events = self.events.get(sid, [])
            return {"events": [e for e in events if e["seq"] > params.get("last_seen", 0)],
                    "latest_seq": len(events), "epoch": "worker", "truncated": False,
                    "open_requests": [q for q in self.questions.values() if q["params"]["session_id"] == sid]}
        if method == "session.recover":
            return {"session_id": sid, "execution": self.executions.get(sid), "epoch": "worker",
                    "info": {"model": self.models[sid], "provider": "local", "usage": {}},
                    "latest_seq": len(self.events.get(sid, [])), "history": {
                        "session_key": sid, "through_row": 0, "version": 0}}
        if method == "request.answer":
            from agent_runtime.conversations.model import ConversationError, Refusal
            key = (sid, params["id"])
            fingerprint = json.dumps(params["result"], sort_keys=True)
            if key in self.answers:
                if self.answers[key] != fingerprint:
                    raise ConversationError(Refusal.INVALID_REQUEST)
                return {"status": "ok"}
            question = self.questions.get(params["id"])
            if not question or question["params"]["session_id"] != sid:
                return {"status": "expired"}
            self.questions.pop(params["id"])
            self.answers[key] = fingerprint
            return {"status": "ok"}
        raise AssertionError(method)

    def event(self, sid, kind, **payload):
        events = self.events.setdefault(sid, [])
        execution = self.executions.get(sid)
        params = {"session_id": sid, "type": kind, "payload": payload, "seq": len(events) + 1}
        if execution:
            params["execution_id"] = execution["id"]
            if kind == "message.complete":
                execution["status"] = payload["status"]
        events.append(params)
        self.receive({"method": "event", "params": params})

    def question(self, sid, rid, method="approval", **params):
        frame = {"jsonrpc": "2.0", "id": rid, "method": method, "params": {"session_id": sid, **params}}
        self.questions[rid] = frame
        self.receive(frame)

    def write(self, frame):
        self.writes.append(frame)
        self.questions.pop(frame.get("id"), None)

    def close(self):
        self.closed = True
        self.alive = self.execution_possible = False


class WorkerFactory:
    def __init__(self):
        self.workers = []

    def __call__(self, home, *, receive, lost):
        peer = NativeWorker(home, receive, lost)
        self.workers.append(peer)
        return peer
