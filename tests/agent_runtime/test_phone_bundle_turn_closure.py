"""The phone bundle ships what a turn, the discussion service and the work engine's start import.

Three defects read on the Android emulator (Eternia lane w1118a-emulator4, hermes e70d33c8d4) passed
every hermes test, because the tests ran the embedded serve with the conftest's parser binding and
judged module presence against a checkout where every module exists:

* RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER — every turn ended ``dispatch_failed HarnessParserUnbound``;
  the bundle shipped no parser tree the turn's argv could parse with;
* RT-PHONE-WORK-ENGINE-START-FAILS-ON-A-MISSING-BATCH-MODULE — the start asked whether the
  ``agent_runtime.batch`` PACKAGE ships (it does: pinned) and then imported ``board_source`` (it does not);
* RT-PHONE-DISCUSSION-SERVICE-NOT-BOUND-IN-THE-APP — the runtime half is in
  ``test_embedded_phone_session.py`` (a discussion call from the phone child, no conftest).

Here the bundle's module set is the packager's own plan for ``bundled-phone`` (the walk, the pinned
switched-off modules it ships anyway, the forced sibling tree) — what ``bundle_profile_package.py``
lays out — and each check is judged against it.

Killing mutations (applied, red recorded, reverted — see the commit message):
* drop ``build_turn_parser``'s import and bind from ``EmbeddedServe.start`` → the turn case reddens
  (``hermes_cli.harness_parts.chat_turn_argv`` is no longer in the bundle);
* ``start_serve_work_engine`` back to ``shipped("agent_runtime.batch")`` → the work-engine case reddens.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.slow_native, pytest.mark.timeout(300)]  # the packager's walk, ~40-70 s


@pytest.fixture(scope="module")
def phone_modules() -> frozenset[str]:
    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_closure import profile_walk
    from scripts.bundles.plan import _with_parents, forced_modules, forced_tree_plan

    manifest = load_profile("bundled-phone")
    walk, index = profile_walk(manifest, parents=True)
    kept = _with_parents(set(walk.kept), index)
    pinned = forced_modules(walk, index)
    shipped = _with_parents(kept | pinned, index)
    return frozenset(shipped | forced_tree_plan(manifest, shipped, pinned))


#: What a phone chat turn imports to reach its handler, and what Intelligence Chat's service is.
TURN_AND_DISCUSSION = (
    "hermes_cli.harness_parts.chat_turn_argv",
    "hermes_cli.harness_parts.persona.chat_turn_message",
    "hermes_cli.harness_parts.persona.chat_coordinator",
    "hermes_cli.harness_parts.serve.argv_lane",
    "agent_runtime.discussions.service",
    "agent_runtime.discussions.rpc",
)


def test_a_phone_turn_and_the_discussion_service_are_in_the_bundle(phone_modules):
    assert [m for m in TURN_AND_DISCUSSION if m not in phone_modules] == []
    # Positive control: the set is the phone's, not a checkout's — the full parser tree is not in it.
    assert "hermes_cli.harness_parts.parser" not in phone_modules
    assert "hermes_cli.harness" not in phone_modules


def _start_work_engine(monkeypatch, present) -> list[str]:
    """``start_serve_work_engine`` with presence answered from *present*; the steps it starts recorded."""
    from agent_runtime import loop_tool_lifecycles, module_presence
    from agent_runtime.work_store import engine, persona_turn
    from hermes_cli.harness_parts.serve import queued_turns

    started: list[str] = []
    probe = lambda module: module in present  # noqa: E731
    monkeypatch.setattr(module_presence, "shipped", probe)
    monkeypatch.setattr(loop_tool_lifecycles, "shipped", probe)
    monkeypatch.setattr(persona_turn, "PersonaTurnExecutor",
                        lambda **_: SimpleNamespace(wake_parked=lambda: None))
    monkeypatch.setattr(engine, "WorkEngine", lambda **hooks: SimpleNamespace(hooks=hooks))
    monkeypatch.setattr(engine, "start_work_engine", lambda **_: started.append("engine"))
    monkeypatch.setattr(queued_turns, "_batch_hooks", lambda session: started.append("batch") or {})
    for step in ("start_serve_scheduler", "start_brain_remote_ticker", "start_realmless_fold_ticker"):
        monkeypatch.setattr(queued_turns, step, lambda *a, _s=step, **k: started.append(_s))
    session = SimpleNamespace(serve_request_home=None, drain_state=None, liveness_stop=None)
    queued_turns.start_serve_work_engine(session)
    return started


def test_the_phone_work_engine_starts_without_the_batch_dispatcher_it_does_not_ship(monkeypatch, phone_modules):
    from agent_runtime.module_presence import BATCH_DISPATCHER_MODULES

    # The phone ships the batch package and Work (both pinned), not the dispatcher's own modules.
    assert "agent_runtime.batch" in phone_modules and "agent_runtime.work" in phone_modules
    assert [m for m in BATCH_DISPATCHER_MODULES if m not in phone_modules]
    started = _start_work_engine(monkeypatch, phone_modules)
    assert "engine" in started and "batch" not in started, started
    # Positive control: an installation with every module builds the dispatcher's hooks.
    everything = phone_modules | set(BATCH_DISPATCHER_MODULES)
    assert "batch" in _start_work_engine(monkeypatch, everything)
