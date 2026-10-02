"""Matched native turns; real dispatch and agents, loopback provider only."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
import threading
import time

from tests.agent_runtime.test_native_conversation_roundtrip import Provider
from tests.hermes_cli.test_harness_serve_drain_order import _Pipe, _Sink

OWNER = "a" * 64
ANSWER = "Local native answer"
PROMPT = "Reply briefly to latency-marker. Do not use tools."


class RuntimeProbe:
    def __init__(self):
        self.reader = _Pipe()
        self.writer = _Sink()
        self.sequence = 0

    def call(self, method, **params):
        self.sequence += 1
        rid = f"probe-{self.sequence}"
        self.reader.send(dict(jsonrpc="2.0", id=rid, method=method, params=params))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            reply = next((row for row in self.writer.frames()
                          if row.get("id") == rid and "jsonrpc" in row), None)
            if reply is not None:
                assert "result" in reply, reply
                return reply["result"]
            time.sleep(.01)
        raise AssertionError(f"No reply to {method}")


@contextmanager
def runtime_probe():
    from hermes_cli.harness_parts.parser import build_parser
    from hermes_cli.harness_parts.serve import serve_loop
    from hermes_cli.harness_parts.serve.argv_lane import bind_harness_parser

    bind_harness_parser(build_parser)
    probe = RuntimeProbe()
    result = {}

    def run():
        result["code"] = serve_loop(probe.reader, probe.writer, socket_lane=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        probe.writer.wait_for("ready")
        yield probe
    finally:
        probe.reader.close()
        thread.join(timeout=30)
        assert not thread.is_alive(), "Probe runtime did not drain"
        assert result.get("code") == 0, result


@contextmanager
def local_profile(monkeypatch):
    from hermes_cli.profiles import get_profile_dir
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))
    Provider.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    home = get_profile_dir("latency-probe")
    home.mkdir(parents=True)
    config = (
        "model:\n  default: test-model\n  provider: custom:local-test\n"
        f"providers:\n  local-test:\n    api: http://127.0.0.1:{server.server_port}/v1\n"
        "    api_key: probe-only\n    discover_models: false\n"
        "dashboard:\n  turn_isolation: false\n"
        "conversations:\n  subprocess_worker: true\n"
        "agent_runtime:\n  persona_chat:\n    hot_sessions_enabled: true\n"
        "mcp_servers: {}\n"
    )
    for destination in (home, get_hermes_home()):
        (destination / "config.yaml").write_text(config, encoding="utf-8")
    try:
        yield home
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def worker_target(probe, home):
    install = probe.call("runtime.conversation.capabilities")["install_id"]
    scope = dict(client_scope=OWNER, profile="latency-probe", install_id=install)
    opened = probe.call("runtime.conversation.open", **scope, key="probe",
                        cwd=str(home), profile_home=str(home))
    return {**scope, "session_id": opened["session_id"]}


def instance_target(probe, home):
    directory = probe.call("runtime.agent.directory")
    agent = next(row for row in directory["agents"]
                 if row["profile"] == "latency-probe" and row["canonical"])
    target = dict(client_scope=OWNER, install_id=directory["install_id"],
                  persona_id=agent["persona_id"], persona_instance_id=agent["instance_id"])
    opened = probe.call("runtime.persona.instance.open_chat", **target,
                        new_session=True, idempotency_key="latency-probe")
    assert opened["client_scope"] == OWNER
    return {**target, "session_id": opened["session_id"], "workspace_id": opened.get("workspace_id")}


def worker_send(probe, target, turn):
    return probe.call("runtime.conversation.send", **target, turn_id=turn,
                      prompt={"text": PROMPT, "images": []})


def worker_read(probe, target, turn):
    state = probe.call("runtime.conversation.read", **target, turn_id=turn, cursor=0)
    return worker_observation(state, turn)


def worker_observation(state, turn):
    visible = any(row["turn_id"] == turn and ANSWER in json.dumps(row) for row in state["events"])
    status = state["turn"]["state"]
    assert status in {"dispatching", "running", "completed"}, state
    return visible, status == "completed"


def instance_send(probe, target, turn):
    result = probe.call("runtime.operator.conversation.message", **target,
                        turn_request_id=turn, message=PROMPT, stream=True)
    assert result["accepted"], result
    return result


def instance_read(probe, target, turn):
    state = probe.call("runtime.operator.conversation.read", **target, turn_request_id=turn)
    return instance_observation(state, turn)


def instance_observation(state, turn):
    expected_answers = ("cold", "warm-1", "warm-2").index(turn) + 1
    answers = sum(ANSWER in row["text"] for row in state["messages"])
    active = [row for row in state["active_turns"] if row["client_message_id"] == turn]
    visible = answers >= expected_answers or ANSWER in json.dumps(active)
    done = state["delivery_observed"] and not state["active_turns"] and not state["delivery_pending"]
    return visible, done


def measure_turn(probe, target, turn, send, read):
    started = time.monotonic()
    send(probe, target, turn)
    admitted = time.monotonic()
    first = None
    while time.monotonic() - started < 60:
        visible, done = read(probe, target, turn)
        observed = time.monotonic()
        if visible and first is None:
            first = observed
        if done:
            assert first is not None, "Turn ended without the provider answer"
            return {"admission_ms": round((admitted - started) * 1000),
                    "first_visible_ms": round((first - started) * 1000),
                    "complete_ms": round((observed - started) * 1000)}
        time.sleep(.025)
    raise AssertionError("Probe turn did not settle")


def instance_timing(target, turn):
    from agent_runtime.mission_chat_turns import mission_chat_turn_record

    record = mission_chat_turn_record(
        session_id=target["session_id"], client_message_id=turn)
    timing = record["profile_timing"]
    assert timing["resident_actor_reused"] in (0, 1)
    return timing


def measure_lane(record_property, monkeypatch, open_target, send, read, details=None):
    with local_profile(monkeypatch) as home, runtime_probe() as probe:
        from agent_runtime.config import load_root_runtime_config

        hot_sessions = load_root_runtime_config().persona_chat.hot_sessions_enabled
        assert hot_sessions
        record_property("hot_sessions_enabled", hot_sessions)
        started = time.monotonic()
        target = open_target(probe, home)
        record_property("open_ms", round((time.monotonic() - started) * 1000))
        for turn in ("cold", "warm-1", "warm-2"):
            timings = measure_turn(probe, target, turn, send, read)
            if details is not None:
                timings["profile_timing"] = details(target, turn)
            record_property(turn, json.dumps(timings, sort_keys=True))
    chats = [(auth, body) for auth, body in Provider.requests if body.get("stream")
             and "latency-marker" in json.dumps(body.get("messages", []))]
    record_property("provider_requests", len(Provider.requests))
    assert len(chats) == 3, "Exactly three streamed turns must reach the provider"
    assert all(auth == "Bearer probe-only" and body["model"] == "test-model" for auth, body in chats)
