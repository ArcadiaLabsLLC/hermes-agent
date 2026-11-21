"""One session on the in-process engine (``conversations.in_process_peer``), driven over the gateway's own methods.

The engine every chat with an agent runs on since RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT.
The retired profile-scoped conversation service used to be these tests' harness; what they pin — recovery,
questions, Stop, profile isolation — is the gateway's, so they drive the gateway directly, as its clients do:
``session.create`` / ``session.resume``, ``prompt.submit``, ``session.recover``, ``request.answer``,
``session.interrupt``, ``session.recovery.history`` / ``.inflight``.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from agent_runtime.conversations.in_process_peer import start_in_process_worker

SOURCE = "eternia_intelligence"


def _model_target(home: Path) -> dict:
    from agent_runtime.provider_configuration import configuration_at

    model = configuration_at(home).get("model")
    if not isinstance(model, dict):
        return {}
    return {key: value for key, value in (("model", model.get("default") or model.get("name")),
                                          ("provider", model.get("provider"))) if isinstance(value, str) and value}


class EngineSession:
    def __init__(self, home: Path, *, cwd: str | None = None, resume: str | None = None, auth_home=None):
        self.frames: list[dict] = []
        self.lost = threading.Event()
        self.peer = start_in_process_worker(Path(home), receive=self.frames.append, lost=self.lost.set,
                                            auth_home=auth_home)
        try:
            if resume is None:
                opened = self.peer.call("session.create", {"cwd": cwd, "source": SOURCE, **_model_target(home)})
                self.stored = opened.get("stored_session_id") or opened.get("session_key")
            else:
                opened = self.peer.call("session.resume", {"session_id": resume, "observe_only": True,
                                                           "omit_messages": True, "source": SOURCE})
                self.stored = resume
            self.sid = opened["session_id"]
        except Exception:
            self.peer.close()
            raise

    def submit(self, text: str, execution_id: str) -> None:
        reply = self.peer.call("prompt.submit", {"session_id": self.sid, "text": text, "reject_if_busy": True,
                                                 "execution_id": execution_id})
        assert reply.get("status") == "streaming", reply

    def recover(self, execution_id: str | None = None) -> dict:
        return self.peer.call("session.recover", {"session_id": self.sid,
                                                  **({"execution_id": execution_id} if execution_id else {})})

    def answer(self, request_id: str, result: dict) -> dict:
        return self.peer.call("request.answer", {"session_id": self.sid, "id": request_id, "result": result})

    def stop(self, execution_id: str) -> dict:
        return self.peer.call("session.interrupt", {"session_id": self.sid, "expected_execution_id": execution_id})

    def inflight(self, **params) -> dict:
        return self.peer.call("session.recovery.inflight", {"session_id": self.sid, **params})

    def history(self, position: dict) -> list[str]:
        """Every stored message of the session, reassembled from its bounded pages."""
        index, offset, rows = 0, 0, {}
        while True:
            page = self.peer.call("session.recovery.history", {"session_id": self.sid, "position": position,
                                                                "message_index": index, "offset": offset})
            for chunk in page["chunks"]:
                prior = rows.get(chunk["index"], "")
                assert len(prior) == chunk["offset"]
                rows[chunk["index"]] = prior + chunk["data"]
            index, offset = page["message_index"], page["offset"]
            if not page["more"]:
                return [rows[key] for key in sorted(rows)]

    def completion(self, execution_id: str) -> dict | None:
        """The ``message.complete`` payload the engine emitted for ``execution_id``, if it has."""
        for frame in list(self.frames):
            params = frame.get("params") or {}
            if (frame.get("method") == "event" and params.get("type") == "message.complete"
                    and params.get("execution_id") == execution_id):
                return params.get("payload") or {}
        return None

    def close(self) -> None:
        self.peer.close()


def until(read, accept, *, timeout: float = 60):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if accept(value):
            return value
        assert time.monotonic() < deadline, f"condition not reached: {value!r}"[:2000]
        time.sleep(.05)
