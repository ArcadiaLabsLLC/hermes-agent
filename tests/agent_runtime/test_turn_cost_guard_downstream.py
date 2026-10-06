"""h-perf-guard: a slower chat turn fails a test.

Every 2026-10-05/06 latency defect -- a demote core per turn, turn-1 bundle rebuilds, inline
catalog walks, a chat turn queued behind parked hydrate riders, a re-sent turn running a second
handler -- was found by reading live logs; nothing failed. This file drives the serve's own path
end to end and fails on any of them:

* the serve's argv lanes (``ArgvLanes._run`` / ``_spawn_chat_turn`` on a real ``RequestPool``)
  dispatch the real parser and handlers (``dispatch_argv``): ``persona instance open-chat
  --new-session``, then three ``mission-chat message --stream`` turns;
* the real ``GPTPersonaRuntime`` -> ``ProfileAgentRunner`` -> ``AIAgent`` sends each turn to a
  loopback Responses server (``tests/fakes/providers/openai_responses.py``) over SSE; only the
  runtime-provider resolve is pointed at it;
* the chat-open prewarm (resident registry on) builds the chat's actor before turn 1, as a serve
  with ``hot_sessions_enabled`` does;
* the stream hub's batch builder (``_batch_frames_with_liveness``) is handed each step's events
  for a room that declared ``persona_chat_turn`` + ``persona_chat_open``, with the resident
  snapshot worker bound.

COUNTS are asserted exactly; spans get generous budgets (about 3x the 2026-10-06 numbers).
Killing mutations (positive control, recorded in the CHANGE commit): ``batch_turn_roots`` answers
``None`` (a demote core per turn); ``_installed_skill_catalog`` walks inline past its TTL (a
turn-path catalog walk); ``submit_accepted`` puts a chat turn on the shared lane (a rider holds
the turn's worker).

h-send-window: the open starts with the serve's skill-catalog memo COLD (its first chat), and
no turn -- turn 0 included -- may walk the catalog or import a module between ``agent_ready``
and ``request_sent``. Killing mutations: ``FIRST_TURN_MODULES`` back to its first three names
(turn 0 imports the Relay binding and ~25 modules); the warm-up's ``skill_catalog`` step
dropped (turn 0 walks the catalog inline).

h-turn1-conn: the fake answers keep-alive (as the live edge does), the pre-connect runs against
it, and turn 0's title upgrade races the turn for the shared pool as it did live. Turn 0 must
ride a pre-opened connection, parse its first event as fast as a warm turn, keep its prewarmed
actor although the persona's name differs from the instance's, write its prompt and tools pin
after ``request_sent``, and send within ``FIRST_TURN_OVER_WARM_MS`` of the slowest warm turn.
Killing mutations: ``PRECONNECT_CONNECTIONS = 1`` (the title takes the one socket: turn 0
``conn=new``); the ``sdk_event_parse`` step dropped (turn 0 ``first_event_lag_ms`` ~14-23); the
prewarm's ``_instance_as_the_send_path_stamps_it`` dropped (the actor is discarded); the
``defer_prewarmed_turn_persist`` seam answering False (no deferred-persist receipt).

h-prep-contention: three stream readers of the chat (one ``hub``, two ``cli``, as live 2026-10-06
19:03) poll and build their frames beside every turn, and another prewarmed actor's keep-warm chain
fires every 50 ms. The readers share ONE turn-section read per section; no keep-warm refresh starts
once the process has sent its first turn (at most one in flight); the warm budget holds. Killing
mutation: ``provider_preconnect._keep_warm``'s ``_PROCESS_REQUEST_SENT`` check dropped (recorded in
the commit).

h-prereq-window: every turn writes ONE ``send_prep_receipt`` (anchor -> request_sent split into
its phase marks), and a warm turn sends within the ABSOLUTE ``WARM_ANCHOR_TO_REQUEST_SENT_MS``,
so a regression that slows every turn alike goes red (the turn-0-vs-warm budget cannot see it).
Killing mutation: a 400 ms sleep planted before every turn's request (recorded in the commit).
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.agent_runtime.test_pool_starve_downstream import _fields, _session
from tests.agent_runtime.test_stream_turn_section import (  # noqa: F401  (``home`` is a fixture)
    DECLARING,
    INSTANCE,
    ROOT,
    _BuildCounter,
    _batch_since,
    _log_end,
    _seed_chat,
    home,
)
from tests.fakes.providers import openai_responses
from tests.fakes.providers.openai_responses import FakeResponsesServer

MODEL = "gpt-5.6-luna"
TURNS = 3
#: The turn the hydrate riders park beside.
RIDER_TURN = 1
#: The turn whose client message id is presented again while its handler runs.
TWIN_TURN = 2
RIDERS = 4

#: Span budgets, ms: about 3x the 2026-10-06 live numbers.
ACCEPT_TO_ANCHOR_MS = 600
FIRST_ANCHOR_TO_REQUEST_SENT_MS = 2500
#: h-prereq-window: ABSOLUTE warm-turn bound. Offline warm turns read 217-359 ms on the 14:34,
#: 16:55 and current builds alike (h-perf-guard's four-copies load check: 314-373); 600 is ~1.6x
#: the worst of those, so a slowdown on every turn of a few hundred ms reads red.
WARM_ANCHOR_TO_REQUEST_SENT_MS = 600
QUEUE_BEHIND_RIDERS_MS = 1000
#: h-turn1-conn: turn 0 sends within this of the slowest warm turn (it was ~150 ms behind).
FIRST_TURN_OVER_WARM_MS = 100
#: h-turn1-conn: first byte -> first parsed event. A cold SDK event parse is 21-23 ms here
#: (277-334 ms in a cold process); a warm one 0.4. The live bar is 50.
FIRST_EVENT_LAG_MS = 8.0
#: How long a turn may sit behind the parked riders before the scenario releases them (so a
#: turn queued behind them still finishes, and reads red on ``queue_ms``).
RIDER_HOLD_S = 5.0
#: The title upgrade's answer time on the fake (live: ~1 s): the connection it holds is busy
#: while turn 1 sends.
TITLE_CALL_S = 1.0


def _seed_persona() -> None:
    from agent_runtime.personas import AgentPersona
    from agent_runtime.store import AgentStore

    # h-turn1-conn: NOT the name ``_seed_chat``'s ``open_chat`` mints the instance with ("Dev"):
    # the send path's ``ensure_for_personas`` re-stamps it, and the prewarm must sign the row
    # turn 1 signs (it was discarded on ``instance_revision`` before the prewarm made that stamp).
    AgentStore().save(AgentPersona(
        id="dev", display_name="Dev Persona", role="dev", model=MODEL, provider="openai-codex",
        api_mode="codex_responses", toolsets=["file", "search", "terminal"],
        system_prompt_path="agent_runtime/prompts/dev.md",
    ))


class _ConnTaggedRequests(list):
    """``FakeResponsesServer.requests`` whose records name the connection that carried them.

    ``ThreadingHTTPServer`` serves each accepted connection on its own thread, so the
    handler thread's name IS the connection.
    """

    def append(self, record) -> None:  # type: ignore[override]
        record["conn"] = threading.current_thread().name
        threading.current_thread().fake_kind = record["kind"]
        super().append(record)


def _keepalive_handler_for(server):
    """The fake's handler, answering like the live edge: ``Connection: keep-alive`` with a
    ``Content-Length`` on every response (the stream included) and a ``404`` to the
    pre-connect's ``HEAD``. The upstream fake closes after each response, so a pooled
    connection could never be read there."""

    base = _REAL_HANDLER_FOR(server)

    class KeepAlive(base):
        def do_HEAD(self) -> None:  # noqa: N802
            server.requests.append({"path": self.path, "kind": "head", "body": {}, "t": time.time(),
                                    "headers": {k.lower(): v for k, v in self.headers.items()}})
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

        def _render(self, step) -> None:
            if isinstance(step, openai_responses.HttpError):
                return super()._render(step)
            if getattr(threading.current_thread(), "fake_kind", None) == "aux":
                time.sleep(TITLE_CALL_S)  # the title model's own answer time
            if isinstance(step, openai_responses.SoftFail):
                events, limit = openai_responses.soft_fail_events(step), None
            else:
                events, limit = openai_responses.turn_events(step), step.drop_after_events
            body = b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode()
                            for e in (events if limit is None else events[:limit]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

    return KeepAlive


_REAL_HANDLER_FOR = openai_responses._handler_for


def _title_call_on_the_shared_pool(monkeypatch, fake) -> None:
    """Turn 1's title upgrade as it runs live: a Responses request on the auxiliary client's
    keep-alive client -- the SAME process-shared transport as the turn's -- started on its own
    thread before the model request, and answered slowly (live: ~1 s).

    The live 14:34 / 14:54 Neko turn 1 lost its pre-connected socket to it: the title thread
    reached the pool first and the turn opened a new connection (``tls_done_ms`` 1378 / 1070).
    """

    import openai

    from agent import title_generator
    from agent.process_bootstrap import build_keepalive_http_client

    titled: list[float] = []

    def call_llm(**_kwargs):
        titled.append(time.monotonic())
        client = openai.OpenAI(api_key="test-key", base_url=fake.base_url, max_retries=0,
                               http_client=build_keepalive_http_client(fake.base_url))
        for _ in client.responses.create(model=MODEL, input="name this chat", stream=True):
            pass
        message = SimpleNamespace(content='{"title": "Fake title"}', reasoning=None, reasoning_content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(title_generator, "call_llm", call_llm)
    # The scenario's chat root carries a seeded title; a launcher-opened chat has none until
    # turn 1's upgrade names it. Once is the race: the scenario's turns are a few hundred ms
    # apart, so a 1 s title on every turn would hold both sockets at once (live turns are
    # seconds apart and read ``pooled``).
    monkeypatch.setattr(title_generator, "_has_upgraded_title", lambda *_a, **_k: bool(titled))


class _Log(logging.Handler):
    """Every receipt the scenario reads."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())

    def receipts(self, prefix: str) -> list[str]:
        return [message for message in self.lines if message.startswith(prefix)]


class _Serve:
    """The serve's lanes; the dispatch records handlers, parks riders and presents a twin."""

    def __init__(self, monkeypatch, capsys) -> None:
        from hermes_cli.harness_parts.serve.argv_lane import dispatch_argv
        from hermes_cli.harness_parts.serve.request_pool import RequestPool
        from tools import skills_tool

        self.capsys = capsys
        self.handlers: dict[str, list[str]] = {}
        self.walks: list[str] = []
        self.release_riders = threading.Event()
        self.riders_parked = threading.Semaphore(0)
        real_walk = skills_tool._find_all_skills

        def counted_walk(*args, **kwargs):
            self.walks.append(threading.current_thread().name)
            return real_walk(*args, **kwargs)

        monkeypatch.setattr(skills_tool, "_find_all_skills", counted_walk)

        def dispatch(argv: list[str]) -> int:
            if argv[1] == "stream":  # a hydrate rider, parked on a snapshot build
                self.riders_parked.release()
                self.release_riders.wait(60)
                return 0
            if argv[1:3] == ["mission-chat", "message"]:
                message_id = argv[argv.index("--client-message-id") + 1]
                self.handlers.setdefault(message_id, []).append(threading.current_thread().name)
                if message_id == f"m-{TWIN_TURN}" and len(self.handlers[message_id]) == 1:
                    self._present_twin(argv)
            return dispatch_argv(argv)

        self.pool = RequestPool(RIDERS)
        self.session, self.frames = _session(dispatch, self.pool)

    def _present_twin(self, argv: list[str]) -> None:
        """The launcher's re-send of a turn whose handler is running (live 2026-10-06 12:04)."""

        from hermes_cli.harness_parts.serve.argv_lane import _ArgvRequest

        twin = threading.Thread(target=self.session._run, args=(_ArgvRequest("twin", list(argv)),))
        twin.start()
        twin.join(30)

    def run(self, rid: str, argv: list[str]) -> int | None:
        from hermes_cli.harness_parts.serve.argv_lane import _ArgvRequest
        from hermes_cli.harness_parts.serve.lanes import submit_accepted

        submit_accepted(self.pool, self.session._run, _ArgvRequest(rid, argv)).result(60)
        return self._exit(rid)

    def park_riders(self) -> None:
        from hermes_cli.harness_parts.serve.argv_lane import _ArgvRequest
        from hermes_cli.harness_parts.serve.lanes import submit_accepted

        self.release_riders.clear()
        for index in range(RIDERS):
            submit_accepted(self.pool, self.session._run, _ArgvRequest(f"ride-{index}", ["harness", "stream"]))
        for _ in range(RIDERS):
            assert self.riders_parked.acquire(timeout=10), "a hydrate rider never reached a worker"

    def turn(self, index: int) -> tuple[int | None, dict]:
        rid = f"turn-{index}"
        from hermes_cli.harness_parts.serve.lanes import ArgvLanes

        ArgvLanes._spawn_chat_turn(
            self.session, SimpleNamespace(emit=self.frames.append), None, rid,
            ["harness", "mission-chat", "message", "--persona", "dev", "--persona-instance-id", INSTANCE,
             "--message", f"hello {index}", "--client-message-id", f"m-{index}", "--stream", "--json"],
            f"t-{index}",
        )
        spawned = time.monotonic()
        while self._exit(rid) is None:
            if time.monotonic() - spawned > 120:
                raise AssertionError(f"{rid} never exited")
            if time.monotonic() - spawned > RIDER_HOLD_S:
                self.release_riders.set()
            time.sleep(0.02)
        self.release_riders.set()
        final: dict = {}
        for line in self.capsys.readouterr().out.splitlines():
            if line.startswith("{") and '"chat.final"' in line:
                final = json.loads(line)
        return self._exit(rid), final

    def _exit(self, rid: str) -> int | None:
        codes = [f.get("code") for f in self.frames if f.get("id") == rid and f.get("event") == "exit"]
        return codes[-1] if codes else None

    def close(self) -> None:
        self.release_riders.set()
        self.pool.shutdown(wait=True)


class _SendPathImports:
    """Modules first imported between a turn's ``agent_ready`` and ``request_sent`` marks.

    Count, not time: every one is a lazy import the chat-open prewarm could have paid
    (``agent_runtime.first_turn_warmup.FIRST_TURN_MODULES``); live turn 1 paid 111-422 ms
    of them (h-send-window).
    """

    def __init__(self, monkeypatch) -> None:
        from agent_runtime.mission_chat_phases import TurnPhaseMarks

        self.turns: dict[int, list[str]] = {}
        self._open: dict[int, set[str]] = {}
        self._turn = 0
        real = TurnPhaseMarks.mark

        def mark(marks, name):
            value = real(marks, name)
            if name == "agent_ready":
                self._open[id(marks)] = set(sys.modules)
            elif name == "request_sent" and id(marks) in self._open:
                self.turns[self._turn] = sorted(set(sys.modules) - self._open.pop(id(marks)))
            elif name == "projected":
                self._turn += 1
            return value

        monkeypatch.setattr(TurnPhaseMarks, "mark", mark)


def _stream_gate(start: int, builds: _BuildCounter) -> tuple[list[str], int, int]:
    """The hub's frames for every event since ``start``, for a room that declared the turn and
    open overlays: ``(frame types, build bodies run, last offset)``."""

    from agent_runtime.patch_coverage import PERSONA_CHAT_OPEN_CAPABILITY
    from agent_runtime.stream.build import _batch_frames_with_liveness

    batch = _batch_since(start)
    if not batch:
        return [], 0, start
    before = builds.calls
    frames = list(_batch_frames_with_liveness(
        batch, base_offset=start, delta_patches=True, resync=False, heartbeat_interval_seconds=60,
        fold_entities=sorted(set(DECLARING) | {PERSONA_CHAT_OPEN_CAPABILITY}),
    ))
    types = [frame.get("type") for frame in frames if frame.get("type") != "heartbeat"]
    return types, builds.calls - before, batch[-1][0]


class _Readers:
    """h-prep-contention: the live serve's three stream readers of one chat (one ``hub``, two
    ``cli`` -- 2026-10-06 19:03), each polling the log and building its frames for every new batch
    while the turns run, as the serve's producers do."""

    CALLERS = ("hub", "cli", "cli")
    POLL_S = 0.1

    def __init__(self, offset: int) -> None:
        import agent_runtime.snapshot_turn_yield  # noqa: F401  (the readers' lazy imports)
        import agent_runtime.turn_section_read  # noqa: F401
        from agent_runtime.running_work import build_running_work

        build_running_work()  # live readers were attached long before the chat; their imports are paid
        self.stop = threading.Event()
        self.frames: list[str] = []
        self.threads = [threading.Thread(target=self._read, args=(caller, offset), daemon=True,
                                         name=f"stream-reader-{index}-{caller}")
                        for index, caller in enumerate(self.CALLERS)]
        for thread in self.threads:
            thread.start()

    def _read(self, caller: str, offset: int) -> None:
        from agent_runtime.patch_coverage import PERSONA_CHAT_OPEN_CAPABILITY
        from agent_runtime.stream.build import _batch_frames_with_liveness

        while not self.stop.wait(self.POLL_S):
            batch = _batch_since(offset)
            if not batch:
                continue
            for frame in _batch_frames_with_liveness(
                batch, base_offset=offset, delta_patches=True, resync=False, heartbeat_interval_seconds=60,
                fold_entities=sorted(set(DECLARING) | {PERSONA_CHAT_OPEN_CAPABILITY}), caller=caller,
            ):
                self.frames.append(str(frame.get("type")))
            offset = batch[-1][0]

    def close(self) -> None:
        self.stop.set()
        for thread in self.threads:
            thread.join(30)


def _arm_other_actor_keepwarm(monkeypatch, base_url: str):
    """Another prewarmed actor's keep-warm chain (live: eight chains from one prewarm pass),
    firing every 50 ms instead of every 15 s so it is inside every turn's window."""

    import httpx

    from agent_runtime import provider_preconnect

    monkeypatch.setattr(provider_preconnect, "KEEPWARM_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(provider_preconnect, "KEEPWARM_MAX_REFRESHES", 10_000)
    http = httpx.Client()
    other = SimpleNamespace(session_api_calls=0, _api_call_count=0)
    provider_preconnect._keep_warm(other, http, base_url, "other-actor", {}, (0, 0))
    return http


def _await_prewarm(log: _Log, root: str) -> str:
    deadline = time.monotonic() + 120
    while True:
        done = [m for m in log.receipts("persona_chat_actor_prewarm root=") if f"root={root} " in m]
        if done:
            return _fields(done[0])["outcome"]
        if time.monotonic() > deadline:
            raise AssertionError(f"the open's prewarm of {root} never finished")
        time.sleep(0.05)


def _prefix_breaks(bodies: list[dict]) -> list[str]:
    """Turn N+1's request opens with turn N's bytes: the same tools, instructions and cache key,
    and turn N's input as its own first items."""

    breaks = []
    for n, (before, after) in enumerate(zip(bodies, bodies[1:])):
        for key in ("tools", "instructions", "prompt_cache_key", "model", "reasoning", "include"):
            if json.dumps(before.get(key), sort_keys=True) != json.dumps(after.get(key), sort_keys=True):
                breaks.append(f"turn {n}->{n + 1}: request {key} moved")
        earlier, later = before.get("input") or [], after.get("input") or []
        if json.dumps(later[:len(earlier)]) != json.dumps(earlier):
            moved = [i for i, (a, b) in enumerate(zip(earlier, later)) if a != b]
            breaks.append(f"turn {n}->{n + 1}: input item(s) {moved or 'dropped'} rewritten")
    return breaks


@pytest.mark.timeout(240)
def test_a_new_chat_and_three_turns_stay_inside_the_turn_cost_guard(
    monkeypatch, capsys, isolate_agent_runtime_root, home  # noqa: F811
):
    from agent_runtime import provider_preconnect
    from agent_runtime.persona_chat_continuity.runtime_registry import (
        initialize_persona_chat_runtime_registry,
    )
    from agent_runtime.profile_runner import execute
    from agent_runtime.prompt_observability import skills_resolver
    from agent_runtime.snapshot_worker import executor as executor_mod
    from hermes_constants import get_hermes_home

    root_logger = logging.getLogger()
    log = _Log()
    previous_level = root_logger.level
    root_logger.addHandler(log)
    root_logger.setLevel(logging.INFO)
    builds = _BuildCounter(monkeypatch)
    send_imports = _SendPathImports(monkeypatch)
    violations: list[str] = []
    budgets: list[str] = []
    spans: list[str] = []
    started = time.monotonic()

    # The live edge keeps a connection open; the pre-connect opens one (loopback included here).
    monkeypatch.setattr(openai_responses, "_handler_for", _keepalive_handler_for)
    monkeypatch.setattr(provider_preconnect, "_is_loopback", lambda host: False)
    fake = FakeResponsesServer(default_text="hi there")
    _title_call_on_the_shared_pool(monkeypatch, fake)
    fake.requests = _ConnTaggedRequests()
    with fake as provider:
        monkeypatch.setattr(execute, "resolve_runtime_provider", lambda **_kw: {
            "provider": "openai-codex", "api_mode": "codex_responses", "base_url": provider.base_url,
            "api_key": "test-key", "model": MODEL})
        execute._RUNTIME_RESOLVE_CACHE.clear()
        _seed_persona()
        _seed_chat()  # the agent and its previous chat
        initialize_persona_chat_runtime_registry()
        assert executor_mod.bind(Path(get_hermes_home())), "the snapshot worker is off"
        # The serve's worker is warm long before an operator opens a chat.
        warm_worker = threading.Thread(target=executor_mod.bound_binding().turn_section, args=(ROOT,),
                                       kwargs={"named": (INSTANCE,), "evict": 1}, daemon=True)
        warm_worker.start()
        readers = keepwarm_http = None
        serve = _Serve(monkeypatch, capsys)
        try:
            # ── the new chat ──────────────────────────────────────────────────
            # The serve's catalog memo is COLD on its first chat: the hub's builds, its only other
            # reader, run in the snapshot worker process (h-send-window: live turn 1 walked 312 ms).
            skills_resolver._skill_catalog_memo.update(at=0.0, rows=None, walker=None)
            start = _log_end()
            assert serve.run("open-1", [
                "harness", "persona", "instance", "open-chat", "--persona", "dev",
                "--persona-instance-id", INSTANCE, "--new-session", "--idempotency-key", "guard", "--json",
            ]) == 0
            root = json.loads(capsys.readouterr().out)["session_id"]
            outcome = _await_prewarm(log, root)
            warm_worker.join(60)
            types, cores, offset = _stream_gate(start, builds)
            cores = max(cores, len(log.receipts("snapshot_build_core ")))
            if cores or "delta" in types:
                violations.append(f"chat open: {cores} full snapshot core(s), frames {types}")
            if outcome != "warmed":
                violations.append(f"chat open: prewarm outcome={outcome}")

            # h-prep-contention: three readers of the chat and another actor's keep-warm run
            # beside every turn, as they did live.
            provider_preconnect._PROCESS_REQUEST_SENT.clear()
            keepwarm_http = _arm_other_actor_keepwarm(monkeypatch, provider.base_url)
            readers = _Readers(offset)

            # ── three turns ───────────────────────────────────────────────────
            sections_seen = len(log.receipts("turn_section "))
            windows_seen = len(log.receipts("send_window_receipt "))
            deferred_seen = len(log.receipts("first_turn_persist_deferred "))
            sent_by_turn: dict[int, int] = {}
            for index in range(TURNS):
                if index:  # past the TTL: a warm turn answers stale, never walks inline
                    skills_resolver._skill_catalog_memo["at"] = time.monotonic() - 60.0
                if index == RIDER_TURN:
                    serve.park_riders()
                serve.walks.clear()
                cores_before = len(log.receipts("snapshot_build_core "))
                code, final = serve.turn(index)
                timing = final.get("timing") or {}
                if code != 0 or final.get("reply") != "hi there":
                    violations.append(f"turn {index}: exit {code}, reply {final.get('reply')!r}")
                    continue

                types, cores, offset = _stream_gate(offset, builds)
                cores = max(cores, len(log.receipts("snapshot_build_core ")) - cores_before)
                if cores or types != ["persona_chat_turn"]:
                    violations.append(f"turn {index}: {cores} full snapshot core(s), frames {types}")
                sections = log.receipts("turn_section ")[sections_seen:]
                sections_seen += len(sections)
                built = [_fields(s) for s in sections if _fields(s).get("source") == "built"]
                executors = [b.get("executor") for b in built]
                offsets = [b.get("offset") for b in built]
                if len(offsets) != len(set(offsets)):
                    violations.append(f"turn {index}: {len(offsets)} turn-section reads for offsets {offsets} "
                                      f"({len(_Readers.CALLERS)} readers of one root share one read per section)")
                if not executors or set(executors) != {"worker"}:
                    violations.append(f"turn {index}: turn-section read on the stream thread: {executors}")
                if index == 0 and timing.get("visibility_bundle_builds") != 0:
                    violations.append(f"turn 0: visibility_bundle_builds={timing.get('visibility_bundle_builds')}")
                deferred = [_fields(m) for m in log.receipts("first_turn_persist_deferred ")[deferred_seen:]]
                deferred_seen += len(deferred)
                expected = [{"ran_on": "request_sent"}] if index == 0 else []
                if [{"ran_on": d.get("ran_on")} for d in deferred] != expected:
                    violations.append(f"turn {index}: first-turn persist receipts {deferred} (turn 0 writes its "
                                      "prompt and tools pin after request_sent, once)")
                if index == 0 and timing.get("resident_actor_reused") is not True:
                    violations.append("turn 0: the prewarmed actor was not reused")
                turn_thread = serve.handlers[f"m-{index}"][0]
                inline = [name for name in serve.walks if name == turn_thread]
                if send_imports.turns.get(index):
                    violations.append(f"turn {index}: imported {send_imports.turns[index]} between agent_ready "
                                      "and request_sent (the prewarm's first-turn warm-up owns them)")
                if inline:
                    violations.append(f"turn {index}: {len(inline)} inline catalog walk(s) on the turn's thread")
                windows = [_fields(m) for m in log.receipts("send_window_receipt ")[windows_seen:]]
                windows_seen += len(windows)
                if [w.get("conn") for w in windows] != ["reused"]:
                    violations.append(f"turn {index}: send_window conn={[w.get('conn') for w in windows]} "
                                      "(the pre-opened connections are the ones every turn rides)")
                lag = windows[0].get("first_event_lag_ms") if windows else None
                if lag in (None, "na") or float(lag) > FIRST_EVENT_LAG_MS:
                    budgets.append(f"turn {index}: first_event_lag_ms={lag} > {FIRST_EVENT_LAG_MS} "
                                   "(the SDK's first event parse belongs to the prewarm)")

                anchor = [_fields(m) for m in log.receipts(f"chat_turn_accept_to_anchor request=turn-{index} ")]
                if not anchor:
                    violations.append(f"turn {index}: no chat_turn_accept_to_anchor receipt")
                    continue
                if index == RIDER_TURN and int(anchor[0]["queue_ms"]) > QUEUE_BEHIND_RIDERS_MS:
                    violations.append(f"turn {index}: queued {anchor[0]['queue_ms']} ms behind "
                                      f"{RIDERS} parked hydrate riders")
                if int(anchor[0]["total_ms"]) > ACCEPT_TO_ANCHOR_MS:
                    budgets.append(f"turn {index}: accept->anchor {anchor[0]['total_ms']} ms "
                                   f"> {ACCEPT_TO_ANCHOR_MS}")
                sent = timing.get("request_sent_ms")
                if isinstance(sent, int):
                    sent_by_turn[index] = sent
                spans.append(f"turn {index} accept->anchor={anchor[0]['total_ms']} anchor->request_sent={sent} "
                             f"conn={windows[0].get('conn') if windows else None} first_event_lag_ms={lag}")
                prep = [_fields(m) for m in log.receipts("send_prep_receipt ") if f" turn=m-{index} " in m]
                if len(prep) != 1 or str(prep[0].get("total_ms")) != str(sent):
                    violations.append(f"turn {index}: send_prep_receipt {prep} (one per turn, total_ms = "
                                      f"request_sent_ms {sent})")
                bound = WARM_ANCHOR_TO_REQUEST_SENT_MS if index else FIRST_ANCHOR_TO_REQUEST_SENT_MS
                if not isinstance(sent, int) or sent > bound:
                    budgets.append(f"turn {index}: anchor->request_sent {sent} ms > {bound}")

            # h-prep-contention: no keep-warm refresh once the process has sent a turn.
            readers.close()
            first_sent = next((i for i, line in enumerate(log.lines) if line.startswith("send_prep_receipt ")), None)
            late = [m for m in log.lines[first_sent or 0:] if m.startswith("persona_chat_actor_prewarm_keepwarm ")]
            # One refresh may have been in flight when the first request left; none may start after it.
            if first_sent is None or len(late) > 1:
                violations.append(f"{len(late)} keep-warm refresh(es) after the process sent its first turn")
            if "persona_chat_turn" not in readers.frames:
                violations.append(f"the attached readers built no turn frames: {readers.frames}")

            warm = [sent_by_turn[i] for i in range(1, TURNS) if i in sent_by_turn]
            if 0 in sent_by_turn and warm and sent_by_turn[0] > max(warm) + FIRST_TURN_OVER_WARM_MS:
                budgets.append(f"turn 0: anchor->request_sent {sent_by_turn[0]} ms > the slowest warm turn "
                               f"{max(warm)} + {FIRST_TURN_OVER_WARM_MS}")

            # ── one handler per client message id ─────────────────────────────
            twin = [f for f in serve.frames if f.get("id") == "twin"]
            if [len(serve.handlers.get(f"m-{i}", ())) for i in range(TURNS)] != [1] * TURNS:
                violations.append(f"handlers per client message id: {serve.handlers}")
            if not any(f.get("error") == "chat_turn_duplicate_in_flight" for f in twin):
                violations.append(f"the re-sent turn was not refused: {twin}")

            bodies = provider.main_requests()
            if len(bodies) != TURNS:
                violations.append(f"{len(bodies)} provider requests for {TURNS} turns")
            violations.extend(_prefix_breaks(bodies))
        finally:
            serve.close()
            if readers is not None:
                readers.close()
            if keepwarm_http is not None:
                keepwarm_http.close()
            executor_mod.unbind()
            # Process state a bundled run's next file must not inherit.
            initialize_persona_chat_runtime_registry(enabled=False)
            execute._RUNTIME_RESOLVE_CACHE.clear()
            root_logger.removeHandler(log)
            root_logger.setLevel(previous_level)

    print(f"turn-cost guard: {time.monotonic() - started:.1f} s; " + "; ".join(spans))
    print("\n".join(log.receipts("send_prep_receipt ")))
    assert not violations, "turn-cost guard (counts):\n  " + "\n  ".join(violations)
    assert not budgets, "turn-cost guard (span budgets):\n  " + "\n  ".join(budgets)
