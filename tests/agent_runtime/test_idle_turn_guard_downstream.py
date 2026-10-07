"""h-idle-turn: the first turn after an idle pause costs what a warm turn costs.

Live 2026-10-07 00:44-00:45 the first turn after 35 s / 2.5 min idle sent in 1139 / 1729 ms on a
NEW connection, the next one 481 ms on a pooled one (``agent_runtime.idle_turn_keeper``). This
drives the turn-cost guard's serve path (``test_turn_cost_guard_downstream``: the real argv lanes,
handlers and ``AIAgent`` against a keep-alive loopback Responses server, the chat-open prewarm):
three warm turns, then an idle pause past every TTL memo the turn window reads and past the
pool's ``keepalive_expiry``, then one turn. The after-idle turn must

* rebuild no memo between its anchor and ``request_sent`` -- no skill-catalog walk on any thread
  (``skills_tool._find_all_skills``), no runtime re-resolve (``resolve_runtime_provider``), no
  ``skill-catalog-refresh`` thread started, no idle keep-warm ``HEAD``;
* ride a pooled connection (``send_window_receipt conn=reused``) although its actor's pre-connect
  record is dropped (h-idle-socket: live, the chat typed in was never pre-connected), and every
  keeper tick sends its ``HEAD`` (an HTTP status, never ``no_target``);
* send within :data:`IDLE_OVER_WARM_MS` of the slowest warm turn and inside the guard's absolute
  warm budget.

The pause is shortened, not faked: the upstream skills memo and the runtime-resolve memo get a
20 s TTL (the catalog memo's is 15 s), the keeper ticks every :data:`KEEPER_TICK_S`, and the turn
waits :data:`IDLE_S` -- past all three TTLs and the pool's 20 s ``keepalive_expiry``, which is not
shortened. 120 skills are seeded so a walk inside the window costs what it costs on an operator's
tree. Killing mutations (positive controls, recorded in the CHANGE commit): the idle
``HEAD`` dropped (``conn=new``); the keeper's runtime re-resolve dropped (a resolve inside the
window); the in-window catalog deferral and the keeper's catalog refresh both dropped (a walk on
``skill-catalog-refresh`` inside the window).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import pytest

from tests.agent_runtime import test_turn_cost_guard_downstream as guard
from tests.agent_runtime.test_pool_starve_downstream import _fields
from tests.agent_runtime.test_stream_turn_section import INSTANCE, _seed_chat, home  # noqa: F401
from tests.fakes.providers import openai_responses
from tests.fakes.providers.openai_responses import FakeResponsesServer

#: Past the shortened memo TTLs (15 / 20 / 20 s) and the pool's unshortened 20 s keepalive_expiry.
IDLE_S = 24.0
KEEPER_TICK_S = 4.0
MEMO_TTL_S = 20.0
SKILLS = 120
#: The after-idle turn sends within this of the slowest warm turn (it was 115-450 ms behind).
IDLE_OVER_WARM_MS = 100
WARM_TURNS = (0, 1, 3)  # turn 2 is the guard serve's re-sent twin
IDLE_TURN = 4


def _seed_skills(count: int) -> None:
    from hermes_constants import get_hermes_home

    for index in range(count):
        skill = Path(get_hermes_home()) / "skills" / f"group{index % 6}" / f"idle-skill-{index}"
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: idle-skill-{index}\ndescription: skill {index}\nmetadata:\n  tags: [a, b]\n---\n\nbody\n",
            encoding="utf-8")


class _Windows:
    """Each turn's anchor -> ``request_sent`` interval, and what happened inside it."""

    def __init__(self, monkeypatch) -> None:
        from agent_runtime.mission_chat_phases import TurnPhaseMarks

        self.windows: list[tuple[float, float]] = []
        self.events: list[tuple[float, str]] = []
        opened: dict[int, float] = {}
        real_init, real_mark, real_start = TurnPhaseMarks.__init__, TurnPhaseMarks.mark, threading.Thread.start

        def init(marks, *args, **kwargs):
            opened[id(marks)] = time.monotonic()
            real_init(marks, *args, **kwargs)

        def mark(marks, name):
            value = real_mark(marks, name)
            if name == "request_sent" and id(marks) in opened:
                self.windows.append((opened.pop(id(marks)), time.monotonic()))
            return value

        def start(thread, *args, **kwargs):
            if thread.name == "skill-catalog-refresh":
                self.note("thread skill-catalog-refresh")
            return real_start(thread, *args, **kwargs)

        monkeypatch.setattr(TurnPhaseMarks, "__init__", init)
        monkeypatch.setattr(TurnPhaseMarks, "mark", mark)
        monkeypatch.setattr(threading.Thread, "start", start)

    def note(self, what: str) -> None:
        self.events.append((time.monotonic(), f"{what} on {threading.current_thread().name}"))

    def inside_last(self) -> list[str]:
        opened, sent = self.windows[-1]
        return [what for at, what in self.events if opened <= at <= sent]


@pytest.mark.timeout(240)
def test_the_first_turn_after_an_idle_pause_rebuilds_no_memo_and_rides_a_warm_socket(
    monkeypatch, capsys, isolate_agent_runtime_root, home  # noqa: F811
):
    from agent_runtime import idle_turn_keeper, provider_preconnect
    from agent_runtime.persona_chat_continuity.runtime_registry import (
        initialize_persona_chat_runtime_registry,
    )
    from agent_runtime.profile_runner import execute
    from agent_runtime.snapshot_worker import executor as executor_mod
    from hermes_constants import get_hermes_home
    from tools import skills_tool

    root_logger = logging.getLogger()
    log = guard._Log()
    previous_level = root_logger.level
    root_logger.addHandler(log)
    root_logger.setLevel(logging.INFO)
    windows = _Windows(monkeypatch)
    violations: list[str] = []
    spans: list[str] = []

    monkeypatch.setattr(skills_tool, "_SKILLS_CACHE_TTL_SECONDS", MEMO_TTL_S)
    monkeypatch.setattr(execute, "RUNTIME_RESOLVE_CACHE_TTL_SECONDS", MEMO_TTL_S)
    monkeypatch.setattr(idle_turn_keeper, "KEEPER_INTERVAL_SECONDS", KEEPER_TICK_S)
    monkeypatch.setattr(idle_turn_keeper, "KEEPER_MAX_TICKS", 100)
    monkeypatch.setattr(openai_responses, "_handler_for", guard._keepalive_handler_for)
    monkeypatch.setattr(provider_preconnect, "_is_loopback", lambda host: False)
    real_walk = skills_tool._find_all_skills
    real_head = provider_preconnect.refresh_idle_connection

    def head(agent):
        windows.note("idle keep-warm HEAD")
        return real_head(agent)

    monkeypatch.setattr(provider_preconnect, "refresh_idle_connection", head)
    fake = FakeResponsesServer(default_text="hi there")
    fake.requests = guard._ConnTaggedRequests()
    with fake as provider:
        def resolve(**_kw):
            windows.note("runtime resolve")
            return {"provider": "openai-codex", "api_mode": "codex_responses", "base_url": provider.base_url,
                    "api_key": "test-key", "model": guard.MODEL}

        monkeypatch.setattr(execute, "resolve_runtime_provider", resolve)
        execute._RUNTIME_RESOLVE_CACHE.clear()
        guard._seed_persona()
        _seed_chat()
        _seed_skills(SKILLS)
        initialize_persona_chat_runtime_registry()
        assert executor_mod.bind(Path(get_hermes_home())), "the snapshot worker is off"
        serve = guard._Serve(monkeypatch, capsys)  # counts walks on its own wrapper

        def walk(*args, **kwargs):
            windows.note("skill catalog walk")
            return real_walk(*args, **kwargs)

        monkeypatch.setattr(skills_tool, "_find_all_skills", walk)
        sent: dict[int, int] = {}
        try:
            assert serve.run("open-1", [
                "harness", "persona", "instance", "open-chat", "--persona", "dev",
                "--persona-instance-id", INSTANCE, "--new-session", "--idempotency-key", "idle", "--json",
            ]) == 0
            root = json.loads(capsys.readouterr().out)["session_id"]
            assert guard._await_prewarm(log, root) == "warmed"
            # h-idle-socket: the chat that turns was never pre-connected (live 2026-10-07 12:07 its
            # prewarm read skipped_turn_active); the keeper must keep the client its turns rode.
            provider_preconnect._IDLE_TARGETS.clear()
            for index in (*WARM_TURNS, IDLE_TURN):
                if index == IDLE_TURN:
                    idle_from = time.monotonic()
                    time.sleep(IDLE_S)
                    # Start on a tick boundary, as an operator's message lands between ticks.
                    ticks = len(log.receipts("idle_turn_keeper "))
                    deadline = time.monotonic() + KEEPER_TICK_S * 2
                    while len(log.receipts("idle_turn_keeper ")) == ticks and time.monotonic() < deadline:
                        time.sleep(0.02)
                    spans.append(f"idle {time.monotonic() - idle_from:.1f} s")
                windows_seen = len(log.receipts("send_window_receipt "))
                code, final = serve.turn(index)
                timing = final.get("timing") or {}
                if code != 0 or final.get("reply") != "hi there":
                    violations.append(f"turn {index}: exit {code}, reply {final.get('reply')!r}")
                    continue
                sent[index] = timing.get("request_sent_ms")
                conn = [_fields(m).get("conn") for m in log.receipts("send_window_receipt ")[windows_seen:]]
                inside = windows.inside_last()
                spans.append(f"turn {index} anchor->request_sent={sent[index]} conn={conn} inside={inside}")
                if index == IDLE_TURN:
                    if conn != ["reused"]:
                        violations.append(f"after-idle turn: send_window conn={conn} (the idle keeper keeps one "
                                          "connection of the last active chat warm)")
                    if inside:
                        violations.append(f"after-idle turn: {inside} between anchor and request_sent "
                                          "(memos are refreshed between turns, never inside one)")
        finally:
            serve.close()
            idle_turn_keeper.stop()
            executor_mod.unbind()
            initialize_persona_chat_runtime_registry(enabled=False)
            execute._RUNTIME_RESOLVE_CACHE.clear()
            root_logger.removeHandler(log)
            root_logger.setLevel(previous_level)

    print("idle-turn guard: " + "; ".join(spans))
    print("\n".join(log.receipts("send_prep_receipt ")))
    print("\n".join(log.receipts("idle_turn_keeper ")))
    sockets = sorted({_fields(m).get("socket") for m in log.receipts("idle_turn_keeper ")})
    if not sockets or not all(str(status).isdigit() for status in sockets):
        violations.append(f"idle keeper socket statuses {sockets} (every tick sends its HEAD on the "
                          "client the last turn rode, pre-connected or not)")
    warm = [sent[i] for i in WARM_TURNS[1:] if isinstance(sent.get(i), int)]
    after = sent.get(IDLE_TURN)
    if not warm or not isinstance(after, int):
        violations.append(f"missing request_sent_ms: {sent}")
    else:
        if after > max(warm) + IDLE_OVER_WARM_MS:
            violations.append(f"after-idle turn: anchor->request_sent {after} ms > the slowest warm turn "
                              f"{max(warm)} + {IDLE_OVER_WARM_MS}")
        if after > guard.WARM_ANCHOR_TO_REQUEST_SENT_MS:
            violations.append(f"after-idle turn: anchor->request_sent {after} ms > "
                              f"{guard.WARM_ANCHOR_TO_REQUEST_SENT_MS}")
    assert not violations, "idle-turn guard:\n  " + "\n  ".join(violations)
