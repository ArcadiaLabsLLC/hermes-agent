"""h-warm-phases: a warm chat turn over live-sized skill roots walks none of them before its request leaves.

Live 2026-10-06 20:30 the warm turns of one Neko chat took 748-1146 ms from the handler's anchor to
``request_sent``; the offline turn-cost guard read 214-359 ms for the same code, because its home has
no skills. The difference was data: every turn re-walked every skill root it resolved against (one
``os.scandir`` per directory; the operator's roots hold ~800 directories) in ``context_built`` and
again in ``observability_built``, rebuilt the shared skill catalog for its observability row, and
re-listed site-packages for its provider-health check.

This file seeds roots of that size (synthetic) and drives the serve's own path -- the argv lanes, the
chat-open prewarm, three ``mission-chat message --stream`` turns against the loopback Responses fake
(``test_turn_cost_guard_downstream``'s scaffolding) -- and asserts, for every warm turn, inside its
anchor -> ``request_sent`` window: no skill-root walk, no shared-catalog build and no site-packages
listing on any thread but the deferred re-walk's, and the window under :data:`WARM_BUDGET_MS`.

Killing mutation (recorded in the CHANGE commit): ``run.py`` handing the turn a plain ``dict``
instead of ``TurnRootRegistries`` (every warm turn walks its roots and rebuilds the catalog).
"""

from __future__ import annotations

import json
import logging
import threading
import time

import pytest

from tests.agent_runtime import test_turn_cost_guard_downstream as guard
from tests.agent_runtime.test_stream_turn_section import INSTANCE, _seed_chat, home  # noqa: F401
from tests.fakes.providers import openai_responses
from tests.fakes.providers.openai_responses import FakeResponsesServer

TURNS = 3
#: Skills in the head root (two directories and three markdown files each: ~400 / ~600, the
#: operator's neko profile root holds 431 / 898) and in the shared root (186 directories live).
HEAD_SKILLS = 200
SHARED_SKILLS = 90
PERSONA_SKILLS = [f"shared-skill-{index:03d}" for index in range(7)]
#: Warm anchor -> request_sent, ms, on a loaded workstation with the test home's I/O guard on every
#: file call: the cut read 738-1012, the killing mutation 1384-1650. The counts are the guarantee;
#: the budget catches a slowdown that moves no counted call.
WARM_BUDGET_MS = 1200


def _write_skill(root, name: str) -> None:
    skill = root / name
    (skill / "references").mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name} for the guard\n---\n# {name}\n",
                                    encoding="utf-8")
    (skill / "references" / "notes.md").write_text("notes\n", encoding="utf-8")
    (skill / "references" / "more.md").write_text("more\n", encoding="utf-8")


def _seed_skill_roots() -> None:
    from agent_runtime.profile_home import get_shared_skills_dir
    from hermes_constants import get_skills_dir

    head, shared = get_skills_dir(), get_shared_skills_dir()
    for index in range(HEAD_SKILLS):
        _write_skill(head / f"category-{index % 20:02d}", f"head-skill-{index:03d}")
    for index in range(SHARED_SKILLS):
        _write_skill(shared, f"shared-skill-{index:03d}")


def _seed_persona() -> None:
    from agent_runtime.personas import AgentPersona
    from agent_runtime.store import AgentStore

    AgentStore().save(AgentPersona(
        id="dev", display_name="Dev Persona", role="dev", model=guard.MODEL, provider="openai-codex",
        api_mode="codex_responses", skills=list(PERSONA_SKILLS),
        system_prompt_path="agent_runtime/prompts/dev.md",
    ))


class _Windows:
    """Each turn's anchor -> request_sent window, and the per-turn work seen inside it."""

    def __init__(self, monkeypatch) -> None:
        from agent_runtime import skill_resolution, skills_inventory
        from agent_runtime.mission_chat_phases import TurnPhaseMarks
        from agent_runtime.skill_root_freshness import REVALIDATE_THREAD_NAME
        from hermes_cli import venv_integrity

        self.windows: list[list[float | None]] = []
        self.calls: list[tuple[str, float, str]] = []
        self._open: dict[int, int] = {}
        real_init, real_mark = TurnPhaseMarks.__init__, TurnPhaseMarks.mark
        windows, opened = self.windows, self._open

        def init(marks, *args, **kwargs):
            real_init(marks, *args, **kwargs)
            opened[id(marks)] = len(windows)
            windows.append([time.monotonic(), None])

        def mark(marks, name):
            value = real_mark(marks, name)
            if name == "request_sent" and id(marks) in opened:
                windows[opened.pop(id(marks))][1] = time.monotonic()
            return value

        monkeypatch.setattr(TurnPhaseMarks, "__init__", init)
        monkeypatch.setattr(TurnPhaseMarks, "mark", mark)
        for owner, attr, kind in ((skill_resolution, "_skill_root_signature", "skill_root_walk"),
                                  (skills_inventory, "build_shared_catalog", "shared_catalog_build"),
                                  (venv_integrity, "_list_metadata_dirs", "site_packages_listing")):
            self._count(monkeypatch, owner, attr, kind, REVALIDATE_THREAD_NAME)

    def _count(self, monkeypatch, owner, attr, kind, deferred_thread) -> None:
        real = getattr(owner, attr)
        calls = self.calls

        def counted(*args, **kwargs):
            if threading.current_thread().name != deferred_thread:
                calls.append((kind, time.monotonic(), threading.current_thread().name))
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, attr, counted)

    def inside(self, index: int) -> list[str]:
        start, end = self.windows[index]
        return [f"{kind} on {thread}" for kind, at, thread in self.calls
                if end is not None and start <= at <= end]


@pytest.mark.timeout(240)
def test_warm_turns_over_live_sized_skill_roots_walk_nothing_before_request_sent(
    monkeypatch, capsys, isolate_agent_runtime_root, home  # noqa: F811
):
    from agent_runtime import provider_preconnect
    from agent_runtime.persona_chat_continuity.runtime_registry import (
        initialize_persona_chat_runtime_registry,
    )
    from agent_runtime.profile_runner import execute

    root_logger = logging.getLogger()
    log = guard._Log()
    previous_level = root_logger.level
    root_logger.addHandler(log)
    root_logger.setLevel(logging.INFO)
    monkeypatch.setattr(guard, "TWIN_TURN", -1)  # no re-sent turn here
    monkeypatch.setattr(openai_responses, "_handler_for", guard._keepalive_handler_for)
    monkeypatch.setattr(provider_preconnect, "_is_loopback", lambda host: False)
    fake = FakeResponsesServer(default_text="hi there")
    guard._title_call_on_the_shared_pool(monkeypatch, fake)
    problems: list[str] = []
    sent: list[str] = []
    with fake as provider:
        monkeypatch.setattr(execute, "resolve_runtime_provider", lambda **_kw: {
            "provider": "openai-codex", "api_mode": "codex_responses", "base_url": provider.base_url,
            "api_key": "test-key", "model": guard.MODEL})
        execute._RUNTIME_RESOLVE_CACHE.clear()
        _seed_skill_roots()
        _seed_persona()
        _seed_chat()
        initialize_persona_chat_runtime_registry()
        serve = guard._Serve(monkeypatch, capsys)
        windows = None
        try:
            assert serve.run("open-1", [
                "harness", "persona", "instance", "open-chat", "--persona", "dev",
                "--persona-instance-id", INSTANCE, "--new-session", "--idempotency-key", "warm", "--json",
            ]) == 0
            root = json.loads(capsys.readouterr().out)["session_id"]
            guard._await_prewarm(log, root)
            windows = _Windows(monkeypatch)
            for index in range(TURNS):
                code, final = serve.turn(index)
                timing = final.get("timing") or {}
                if code != 0 or final.get("reply") != "hi there":
                    problems.append(f"turn {index}: exit {code}, reply {final.get('reply')!r}")
                    continue
                if not index:
                    continue
                window = windows.inside(index)
                if window:
                    problems.append(f"warm turn {index}: {len(window)} call(s) before request_sent: {window}")
                ms = timing.get("request_sent_ms")
                sent.append(f"turn {index} anchor->request_sent={ms}")
                if not isinstance(ms, int) or ms > WARM_BUDGET_MS:
                    problems.append(f"warm turn {index}: anchor->request_sent {ms} ms > {WARM_BUDGET_MS}")
        finally:
            serve.close()
            initialize_persona_chat_runtime_registry(enabled=False)
            execute._RUNTIME_RESOLVE_CACHE.clear()
            root_logger.removeHandler(log)
            root_logger.setLevel(previous_level)
    print("; ".join(sent))
    print("\n".join(log.receipts("send_prep_receipt ")))
    assert not problems, "warm turns over live-sized skill roots:\n  " + "\n  ".join(problems)
