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
* drop ``"tools.connectors"`` from ``scripts/bundle_profile_closure.py::FACADE_TABLES`` → the tool-call
  case reddens (``tools.connectors.dispatch`` is no longer in the bundle).
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


#: What every tool call imports on its way to its handler: upstream ``model_tools._execute_tool``'s
#: ``from tools.connectors import dispatch_connector_call, is_connector_name``, through the PEP 562 facade.
TOOL_CALL = ("tools.connectors.dispatch", "tools.connectors.gateway.names")


def test_a_phone_tool_calls_facade_import_is_in_the_bundle(phone_modules):
    """RT-PHONE-A-PHONE-CALL-REACHES-ONLY-MODULES-ITS-BUNDLE-SHIPS: every tool call on the emulator failed
    ``No module named 'tools.connectors.dispatch'``; the walk read only ``pm``'s facade table."""
    assert [m for m in TOOL_CALL if m not in phone_modules] == []


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


#: What a phone agent's file tools load: the embedded entry registers them (``EmbeddedServe.start``), and a
#: regex search runs ripgrep's matcher or the ``regex`` fallback.
PHONE_FILE_TOOLS = (
    "agent_runtime.phone_file_tools",
    "agent_runtime.project_files.reader",
    "agent_runtime.project_files.writer",
    "agent_runtime.project_files.native_match",
    "agent_runtime.project_files.fallback_match",
)


def test_the_phone_file_tools_are_in_the_bundle_the_gate_judges(phone_modules):
    """RT-FU-THE-PHONE-GATE-JUDGES-THE-CODE-BEHIND-A-PHONE-AGENTS-FILE-TOOLS: they were registered only by
    the eternia-harness plugin, which a phone does not ship, so the packager's walk (the gate's) never kept
    them. Killing mutation: drop ``ensure_phone_file_tools`` and its import from ``EmbeddedServe.start`` -> red."""
    assert [m for m in PHONE_FILE_TOOLS if m not in phone_modules] == []
    # Positive control: the plugin itself is still not a phone module.
    assert "plugins.eternia_harness" not in phone_modules


def test_three_phone_call_paths_run_on_only_what_the_phone_bundle_ships(phone_modules, tmp_path):
    """RT-PHONE-A-PHONE-CALL-REACHES-ONLY-MODULES-ITS-BUNDLE-SHIPS (d): in a fresh interpreter where every
    first-party module outside the packager's phone plan refuses to import and every spawn is refused
    (``_phone_call_paths_child.py``, the installed profile made the phone's), a phone agent's ``read_file``
    through ``model_tools.handle_function_call``, the identity a resumed chat on a bare custom endpoint asks
    for, and one Work-engine tick each run with no ImportError, no spawn and no warning.

    Killing mutations (applied, red recorded, reverted — see the commit message):
    * drop ``"tools.connectors"`` from ``FACADE_TABLES`` -> the tool-call case reddens;
    * drop ``walk.profile_forced`` from ``plan.forced_modules`` -> the custom-endpoint case reddens;
    * drop the switched-off check from ``engine._default_workspaces`` -> the tick case reddens;
    * skip ``import tools.file_tools`` in ``phone_file_tools.ensure_phone_file_tools`` -> the read after
      upstream's module is imported (as the turn-end ``forget_file_state`` does) runs upstream's, red."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    from scripts.bundle_profile_closure import module_index

    repo = Path(__file__).resolve().parents[2]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"modules": sorted(phone_modules),
                                "tops": sorted({m.split(".")[0] for m in module_index()} - {"tests"})}),
                    encoding="utf-8")
    out = tmp_path / "out.json"
    home = tmp_path / "home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith(("HERMES_", "PYTEST_"))}
    env.update(HERMES_HOME=str(home), PYTHONPATH=str(repo), PYTHONDONTWRITEBYTECODE="1")
    child = Path(__file__).with_name("_phone_call_paths_child.py")
    done = subprocess.run([sys.executable, str(child), str(plan), str(out)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr[-4000:]
    got = json.loads(out.read_text(encoding="utf-8"))
    cases = got["cases"]
    failed = {name: (row.get("error"), row["spawns"]) for name, row in cases.items()
              if "error" in row or row["spawns"]}
    assert failed == {}, {name: cases[name].get("trace") for name in failed}
    reads = cases["tool_call"]["answer"]
    assert reads["registered"] == ["read_file", "write_file", "patch", "search_files"], reads
    for read in (reads["first"], reads["after_upstreams_import"]):
        assert read.get("content") == "1|# Notes\n2|- buy milk", read
    assert cases["custom_endpoint_resume"]["answer"] == "custom"
    # Only the tick's own warning is judged: the checkout's plugin directory scan reports plugins a phone
    # bundle does not hold on disk, which no phone sees.
    assert [w for w in got["warnings"] if "work engine" in w or w.startswith("agent_runtime.work")] == [], got["warnings"]
