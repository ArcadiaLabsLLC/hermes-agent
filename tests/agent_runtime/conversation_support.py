"""Only the native process boundary is doubled; service and SQLite are real."""
import os
import psutil


class NativeWorker:
    def __init__(self, home, receive, lost):
        self.home, self.receive, self.lost = home, receive, lost
        self.alive = self.execution_possible = True
        self.process_identity = (os.getpid(), psutil.Process().create_time())
        self.calls, self.writes = [], []
        self.models = {}
        self.on_submit = None
        self.closed = False

    def call(self, method, params, **_):
        self.calls.append((method, params))
        sid = params.get("session_id")
        if method == "session.create":
            sid = f"native-{len(self.models)}"
            self.models[sid] = "model-a"
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
            if self.on_submit:
                self.on_submit(sid)
            return {"status": "streaming"}
        raise AssertionError(method)

    def event(self, sid, kind, **payload):
        self.receive({"method": "event", "params": {
            "session_id": sid, "type": kind, "payload": payload}})

    def question(self, sid, rid, method="approval", **params):
        self.receive({"jsonrpc": "2.0", "id": rid, "method": method,
                      "params": {"session_id": sid, **params}})

    def write(self, frame):
        self.writes.append(frame)

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
