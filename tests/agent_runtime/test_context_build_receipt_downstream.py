"""r-turn: ``_build_context`` stamps every part of ``context_built`` on one log receipt.

The ~8 ms of a warm span that ``context_native_history_ms`` and the builder's sub-stamps did
not name (registry, journal abandoned-id read, revision, relay marker, session model config,
builder glue) is now an exclusive lap each, in microseconds, on ``context_build_receipt``.

*Killing mutations:* drop ``laps.lap("builder")`` in ``_build_context`` -> the builder part is
absent and the slow builder's time lands nowhere, red; drop ``laps.emit(...)`` -> no receipt, red;
lap from the build's start instead of the last lap (non-exclusive) -> the parts sum past the
total, red.
"""

from __future__ import annotations

import logging
import re
import time
import types

from agent_runtime.context_build_receipt import CONTEXT_BUILD_PARTS, ContextBuildLaps
from tests.agent_runtime.test_native_revision_of_read import HISTORY, ROOT, _CountingSessionDB


def _run_build_context(monkeypatch, builder_sleep_s: float):
    import agent_runtime.mission_chat_turn_context as turn_context_module
    from hermes_cli.harness_parts.persona.chat_turn_commit import run as run_module

    monkeypatch.setattr(run_module, "abandoned_mission_chat_message_ids", lambda session_id: set())
    monkeypatch.setattr(run_module, "persona_chat_runtime_registry", lambda: None)
    monkeypatch.setattr(run_module, "_resolve_relay_sender_marker", lambda *a, **k: None)
    monkeypatch.setattr(run_module, "_session_model_config", lambda db, sid: {})
    monkeypatch.setattr(run_module, "resolve_mission_chat_max_seconds", lambda value: 240)

    def _slow_builder(**kwargs):
        time.sleep(builder_sleep_s)
        return types.SimpleNamespace()

    monkeypatch.setattr(turn_context_module, "build_mission_chat_turn_context", _slow_builder)
    commit = types.SimpleNamespace(
        args=types.SimpleNamespace(), session_db=_CountingSessionDB(HISTORY), session_id=ROOT,
        pre_admit_timings={}, instance_store=None, relay_chain_in=None, persona=None, instance=None,
        cfg=None, model_selection={}, relay_deadline=None, turn_relay_chain=(), message="hello",
        client_message_id="turn-ctx-1",
        turn_phases=types.SimpleNamespace(mark=lambda name: None, label=lambda name, value: None),
    )
    run_module._RunPhases._build_context(commit)


def _receipt(caplog) -> dict[str, str]:
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("context_build_receipt ")]
    assert len(lines) == 1, lines
    return dict(re.findall(r"(\w+)=(\S+)", lines[0]))


def test_every_part_of_the_span_is_stamped_and_the_builder_owns_its_time(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="agent_runtime.context_build_receipt")
    _run_build_context(monkeypatch, builder_sleep_s=0.03)
    fields = _receipt(caplog)
    assert fields["turn"] == "turn-ctx-1" and fields["source"] == "read"
    parts = {name: int(fields[f"{name}_us"]) for name in CONTEXT_BUILD_PARTS}
    total = int(fields["total_us"])
    assert parts["builder"] >= 25_000
    assert sum(v for k, v in parts.items() if k != "builder") < 25_000
    assert sum(parts.values()) <= total


def test_a_part_never_reached_is_absent_not_zero(caplog):
    caplog.set_level(logging.INFO, logger="agent_runtime.context_build_receipt")
    laps = ContextBuildLaps()
    laps.lap("registry")
    laps.lap("registry")
    laps.lap("not_a_part")
    laps.emit(None, source="read")
    fields = _receipt(caplog)
    assert "registry_us" in fields and fields["turn"] == "-"
    assert not any(f"{name}_us" in fields for name in CONTEXT_BUILD_PARTS if name != "registry")
    assert "not_a_part_us" not in fields
