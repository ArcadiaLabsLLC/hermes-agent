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
"""

from __future__ import annotations

import json
import logging
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
WARM_ANCHOR_TO_REQUEST_SENT_MS = 1500
QUEUE_BEHIND_RIDERS_MS = 1000
#: How long a turn may sit behind the parked riders before the scenario releases them (so a
#: turn queued behind them still finishes, and reads red on ``queue_ms``).
RIDER_HOLD_S = 5.0


def _seed_persona() -> None:
    from agent_runtime.personas import AgentPersona
    from agent_runtime.store import AgentStore

    # ``display_name`` is the one ``_seed_chat``'s instance carries: a name the send path's
    # store read re-stamps would move ``instance_revision`` and discard the prewarm.
    AgentStore().save(AgentPersona(
        id="dev", display_name="Dev", role="dev", model=MODEL, provider="openai-codex",
        api_mode="codex_responses", toolsets=["file", "search", "terminal"],
        system_prompt_path="agent_runtime/prompts/dev.md",
    ))


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
    violations: list[str] = []
    budgets: list[str] = []
    spans: list[str] = []
    started = time.monotonic()

    with FakeResponsesServer(default_text="hi there") as provider:
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
        serve = _Serve(monkeypatch, capsys)
        try:
            # ── the new chat ──────────────────────────────────────────────────
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

            # ── three turns ───────────────────────────────────────────────────
            sections_seen = len(log.receipts("turn_section "))
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
                executors = [_fields(s).get("executor") for s in sections]
                if not executors or set(executors) != {"worker"}:
                    violations.append(f"turn {index}: turn-section read on the stream thread: {executors}")
                if index == 0 and timing.get("visibility_bundle_builds") != 0:
                    violations.append(f"turn 0: visibility_bundle_builds={timing.get('visibility_bundle_builds')}")
                if index == 0 and timing.get("resident_actor_reused") is not True:
                    violations.append("turn 0: the prewarmed actor was not reused")
                turn_thread = serve.handlers[f"m-{index}"][0]
                inline = [name for name in serve.walks if name == turn_thread]
                if index and inline:
                    violations.append(f"turn {index}: {len(inline)} inline catalog walk(s) on the turn's thread")

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
                spans.append(f"turn {index} accept->anchor={anchor[0]['total_ms']} anchor->request_sent={sent}")
                bound = WARM_ANCHOR_TO_REQUEST_SENT_MS if index else FIRST_ANCHOR_TO_REQUEST_SENT_MS
                if not isinstance(sent, int) or sent > bound:
                    budgets.append(f"turn {index}: anchor->request_sent {sent} ms > {bound}")

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
            executor_mod.unbind()
            # Process state a bundled run's next file must not inherit.
            initialize_persona_chat_runtime_registry(enabled=False)
            execute._RUNTIME_RESOLVE_CACHE.clear()
            root_logger.removeHandler(log)
            root_logger.setLevel(previous_level)

    print(f"turn-cost guard: {time.monotonic() - started:.1f} s; " + "; ".join(spans))
    assert not violations, "turn-cost guard (counts):\n  " + "\n  ".join(violations)
    assert not budgets, "turn-cost guard (span budgets):\n  " + "\n  ".join(budgets)
