"""The conversation worker with no subprocess: ``runtime.conversation.*`` over the in-process peer.

Embedded-hermes plan Stage 2 step 8. The phone profile (``conversations.subprocess_worker:
false``) serves each profile's conversations from the SAME native gateway, dispatched
in-process behind the ``NativePeer`` seam. This is the subprocess round-trip
(``test_native_conversation_roundtrip.py``) run over :func:`start_in_process_worker`:
the same service, real agents, a loopback provider — and no child process at all.

Proven: A/B/A turns complete with each profile's own credentials and history (profile
isolation), the same stored sessions come back (sessions), retirement leaves no
execution possible and a reopen recovers the transcript without running a turn
(recovery), and the process never gained a child.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``InProcessPeer._send`` stops injecting ``profile``            -> red (both profiles share one home).
* ``InProcessPeer.close`` skips ``session.close``                 -> red (execution stays possible).
* ``execution_possible`` answers True for a registered in-process worker -> red (retired peers).
* ``select_worker_factory`` always returns ``start_worker``        -> red.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil
import pytest

from agent_runtime.conversations.in_process_peer import InProcessPeer, start_in_process_worker
from agent_runtime.conversations.model import ConversationError, ConversationScope, Refusal
from agent_runtime.conversations.process_evidence import execution_possible
from agent_runtime.conversations.service import ConversationService

pytestmark = pytest.mark.timeout(180)


class Provider(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, *_):
        pass

    def do_GET(self):
        self._send("application/json", json.dumps({"object": "list", "data": [{"id": "test-model"}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.headers.get("Authorization"), body))
        base = {"id": "r", "object": "chat.completion.chunk", "created": 1, "model": "test-model"}
        rows = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Local native answer"},
                                      "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}]
        self._send("text/event-stream", ("".join("data: " + json.dumps(r) + "\n\n" for r in rows)
                                         + "data: [DONE]\n\n").encode())

    def _send(self, kind, data):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _profiles(port: int, shared: bool) -> dict[str, Path]:
    from hermes_cli.profiles import get_profile_dir

    homes = {}
    for profile in ("a", "b"):
        home = get_profile_dir(profile)
        (home / "skills" / f"review-{profile}").mkdir(parents=True)
        (home / "skills" / f"review-{profile}" / "SKILL.md").write_text(
            f"---\nname: review-{profile}\ndescription: Profile review\n---\nRead only {profile}.\n", encoding="utf-8")
        definitions = ("" if shared else
            f"providers:\n  local-test:\n    api: http://127.0.0.1:{port}/v1\n    api_key: isolated-{profile}\n")
        (home / "config.yaml").write_text(
            "model:\n  default: test-model\n  provider: custom:local-test\n"
            + definitions +
            "dashboard:\n  turn_isolation: false\nmcp_servers: {}\n", encoding="utf-8")
        homes[profile] = home
    return homes


def _settle(service, scope, sid, turn):
    deadline = time.monotonic() + 60
    while (result := service.read(scope, sid, 0, turn))["turn"]["state"] in {"dispatching", "running"}:
        assert time.monotonic() < deadline, "in-process turn did not settle"
        time.sleep(.05)
    return result


@pytest.mark.parametrize("shared", [False, True], ids=["private-provider", "shared-provider"])
def test_a_b_a_turns_sessions_and_recovery_with_no_child_process(tmp_path, shared):
    from hermes_cli.profiles import get_profile_dir

    Provider.requests = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    homes = _profiles(provider.server_port, shared)
    owner = tmp_path / "owner"
    owner.mkdir()
    (owner / "config.yaml").write_text(
        f"providers:\n  local-test:\n    api: http://127.0.0.1:{provider.server_port}/v1\n"
        "    key_env: PRIVATE_LLM_KEY\n    models: [test-model]\n    discover_models: false\n", encoding="utf-8")
    (owner / ".env").write_text("PRIVATE_LLM_KEY=shared-provider\n", encoding="utf-8")
    root = tmp_path / "runtime"
    root.mkdir()
    children_before = {c.pid for c in psutil.Process().children(recursive=True)}
    now = [0.0]
    service = ConversationService(root, "phone-install", profile_home=get_profile_dir,
                                  worker_factory=start_in_process_worker,
                                  auth_home=owner if shared else None,
                                  retention_options={"clock": lambda: now[0]})
    sessions = {}
    try:
        for number, profile in enumerate(("a", "b", "a")):
            scope = ConversationScope("operator", "phone-account", profile)
            opened = service.open(scope, key="chat", cwd=str(tmp_path), expected_home=str(homes[profile]))
            sid = sessions.setdefault(profile, opened["session_id"])
            assert opened["session_id"] == sid
            turn = f"turn-{number}"
            service.send(scope, sid, turn, {"text": f"Reply to marker-{profile}-{number}", "images": []})
            result = _settle(service, scope, sid, turn)
            assert result["turn"]["state"] == "completed", result
            done = [e["frame"]["params"]["payload"] for e in result["events"]
                    if e["turn_id"] == turn and e["frame"].get("params", {}).get("type") == "message.complete"]
            assert done and done[-1]["text"] == "Local native answer"
            catalog = service.skills(scope, sid, "list")
            assert {row["id"] for row in catalog["skills"]} >= {f"review-{profile}"}
            assert not any(row["id"] == f"review-{'b' if profile == 'a' else 'a'}" for row in catalog["skills"])
        chat = [(auth, body) for auth, body in Provider.requests
                if any("marker-" in str(m.get("content", "")) for m in body.get("messages", []))]
        assert len(chat) >= 3
        for auth, body in chat:
            mine = next(p for p in ("a", "b") if f"marker-{p}-" in json.dumps(body))
            assert auth == ("Bearer shared-provider" if shared else f"Bearer isolated-{mine}")
            assert f"marker-{'b' if mine == 'a' else 'a'}-" not in json.dumps(body)
        assert (homes["a"] / "state.db").is_file() and (homes["b"] / "state.db").is_file()
        peers = [entry.live.peer for entry in service._bindings._entries.values()]
        assert peers and all(isinstance(peer, InProcessPeer) for peer in peers)
        assert all(execution_possible(*peer.process_identity) for peer in peers)  # live: evidence says so
        assert all(peer._sessions for peer in peers)  # control: each worker holds sessions it must close
        assert {c.pid for c in psutil.Process().children(recursive=True)} <= children_before

        now[0] = 1000
        deadline = time.monotonic() + 20
        while service._bindings._entries:
            service._bindings.sweep()
            assert time.monotonic() < deadline, "settled sessions did not retire"
            time.sleep(.05)
        assert all(not peer.execution_possible for peer in peers)
        assert not any(execution_possible(*peer.process_identity) for peer in peers)
        assert not service._workers._workers
        before = len(Provider.requests)
        scope = ConversationScope("operator", "phone-account", "a")
        reopened = service.open(scope, key="chat", cwd=str(tmp_path), expected_home=str(homes["a"]),
                                resume=sessions["a"])
        assert reopened["session_id"] == sessions["a"] and reopened["turn"]["state"] == "completed"
        page = service.history(scope, sessions["a"], reopened["recovery"]["history"], 0, 0)
        recovered = "".join(chunk["data"] for chunk in page["chunks"])
        assert "marker-a-0" in recovered and "marker-a-2" in recovered and "marker-b-" not in recovered
        assert len(Provider.requests) == before, "reopening must never execute a turn"
    finally:
        service.close()
        provider.shutdown()
        provider.server_close()


def test_a_home_that_is_not_its_profiles_home_is_refused(tmp_path):
    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir("a")
    home.mkdir(parents=True)
    InProcessPeer(home, receive=lambda _f: None, lost=lambda: None,
                  dispatch=lambda *_a: None).close()  # positive control: the canonical home is served
    with pytest.raises(ConversationError) as refused:
        InProcessPeer(tmp_path, receive=lambda _f: None, lost=lambda: None, dispatch=lambda *_a: None)
    assert refused.value.reason is Refusal.WRONG_OWNER


def test_the_profile_switch_picks_the_worker():
    from hermes_constants import get_hermes_home

    from agent_runtime.conversations.worker import select_worker_factory, start_worker

    assert select_worker_factory() is start_worker  # desktop control
    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"conversations": {"subprocess_worker": False}}), encoding="utf-8")
    assert select_worker_factory() is start_in_process_worker
