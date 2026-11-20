"""The ``persona`` patch every ``persona.updated`` rides beside.

Row RT-FU-ADDING-AN-AGENT-SENDS-EVERY-OPEN-ETERNIA-A-FULL-REFRESH (review
w1118a.63 D2): an agent create writes the new agent's own persona, and its
``persona.updated`` demoted every add to a full core. The event is never covered
bare — it pairs with a ``persona`` patch, and only a declaring client may fold it.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from agent_runtime import state_patches as sp
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.events import EventLog
from agent_runtime.models import AgentPersona
from agent_runtime.patch_coverage import (
    HISTORICAL_FOLD_ENTITIES,
    batch_is_patch_coverable,
    event_required_fold_tokens,
)
from agent_runtime.serde import to_jsonable
from agent_runtime.state_patches import (
    PATCH_OP_REFRESH,
    PATCH_OP_UPSERT,
    PERSONA_ENTITY,
    STATE_PATCHED_EVENT_TYPE,
)
from agent_runtime.store import AgentStore

_DIGEST = "0123456789abcdef01234567"
_COPY_ID = f"agent_{_DIGEST}"


@pytest.fixture
def delta_patches_on(monkeypatch):
    def _loader(*args, **kwargs):
        cfg = load_agent_runtime_config(*args, **kwargs)
        cfg.read_model.delta_patches = True
        return cfg

    monkeypatch.setattr(sp.emit, "load_root_runtime_config", _loader)


def _copy_persona() -> AgentPersona:
    """The record ``create_independent_agent`` writes: ``agent_<digest>`` on ``agent-<digest>``."""

    return AgentPersona(
        id=_COPY_ID,
        display_name="Copied Agent",
        role="agent",
        model="gpt-test",
        provider="openai-codex",
        api_mode="codex_responses",
        system_prompt_path="",
        hermes_profile=f"agent-{_DIGEST}",
    )


def _save_batch(persona: AgentPersona):
    before = [offset for offset, _ in EventLog().iter_from_offset(0)]
    AgentStore().save(persona)
    seen = set(before)
    return [event for offset, event in EventLog().iter_from_offset(0) if offset not in seen]


def test_an_agent_create_ships_its_new_persona_as_a_patch(delta_patches_on, isolate_agent_runtime_root):
    """A copy's first record pairs with a complete ``agents`` row stamped ``created``.

    MUTATION: pass ``created=None`` in ``AgentStore.save`` — the pair becomes a
    refresh and this goes red. MUTATION: drop ``persona.updated`` from
    ``LIVE_COVERED_DOMAIN_EVENT_TYPES`` — the batch stops being coverable.
    """

    batch = _save_batch(_copy_persona())

    assert [event.type for event in batch] == [STATE_PATCHED_EVENT_TYPE, "persona.updated"]
    patch = batch[0].payload
    assert (patch["entity"], patch["id"], patch["op"], patch["created"]) == (
        PERSONA_ENTITY, _COPY_ID, PATCH_OP_UPSERT, True,
    )
    # Byte-parity with the row the very next full core carries for this persona.
    from agent_runtime.snapshot import build_snapshot

    core_rows = [row for row in build_snapshot()["agents"] if row.get("persona_id") == _COPY_ID]
    assert core_rows, "the core lists the copy's persona"
    assert patch["changed"] == to_jsonable(core_rows[0])

    # Covered only for a client that declared it can fold the row.
    assert batch_is_patch_coverable(batch, fold_entities=HISTORICAL_FOLD_ENTITIES | {PERSONA_ENTITY})
    assert not batch_is_patch_coverable(batch, fold_entities=HISTORICAL_FOLD_ENTITIES)


def test_a_persona_edit_pairs_with_a_refresh_and_keeps_its_full_core(delta_patches_on, isolate_agent_runtime_root):
    """An edit moves rows the catalog row cannot carry, so its batch demotes for everyone.

    MUTATION: emit the create upsert for every save (drop ``not stored`` from the
    ``created`` condition) — the edit's batch becomes coverable and this goes red.
    """

    AgentStore().save(_copy_persona())
    batch = _save_batch(replace(AgentStore().get(_COPY_ID), display_name="Renamed Agent"))

    assert [event.type for event in batch] == [STATE_PATCHED_EVENT_TYPE, "persona.updated"]
    assert batch[0].payload["op"] == PATCH_OP_REFRESH
    assert not batch_is_patch_coverable(batch, fold_entities=HISTORICAL_FOLD_ENTITIES | {PERSONA_ENTITY})


def test_a_template_personas_first_record_pairs_with_a_refresh(delta_patches_on, isolate_agent_runtime_root):
    """A non-copy persona also moves ``available_personas``, which the row cannot say.

    MUTATION: make ``persona_create_is_foldable`` answer True — this goes red.
    """

    batch = _save_batch(replace(_copy_persona(), id="plain_template", hermes_profile="plain-template"))

    assert batch[0].payload["op"] == PATCH_OP_REFRESH


def test_persona_updated_needs_the_persona_token():
    """The event free-rides only beside a client that folds its pair.

    MUTATION: drop the ``persona.updated`` entry from
    ``TOKEN_GATED_DOMAIN_EVENT_TYPES`` — the required set goes empty.
    """

    event = type("E", (), {"type": "persona.updated", "payload": {"persona_id": "x"}})()
    assert event_required_fold_tokens(event) == frozenset({PERSONA_ENTITY})


def test_every_persona_updated_rides_beside_its_persona_patch():
    """The one emitter of ``persona.updated`` is the paired helper.

    A second emitter that appended the event bare would let a declaring client
    promote a batch whose persona change nothing carries. MUTATION: put
    ``emit_store_event(..., "persona.updated", ...)`` back in ``AgentStore.save`` or
    ``agent_copy_delete`` — this goes red.
    """

    root = Path(__file__).resolve().parents[2]
    allowed = {
        "agent_runtime/state_patches/persona.py",  # the paired emitter
        "agent_runtime/decision_contract_registry.py",  # the contract
        "agent_runtime/patch_coverage.py",  # the coverage tables
    }
    literal = re.compile(r"""["']persona\.updated["']""")
    offenders = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for folder in ("agent_runtime", "hermes_cli", "gateway", "tui_gateway")
        for path in (root / folder).rglob("*.py")
        if literal.search(path.read_text(encoding="utf-8", errors="replace"))
        and str(path.relative_to(root)).replace("\\", "/") not in allowed
    )
    assert offenders == []


def test_an_agent_create_projects_its_row_before_its_record_lands(
    delta_patches_on, isolate_agent_runtime_root, monkeypatch
):
    """The slow projection runs before the write, so the record never waits for its event.

    Row RT-FU-ADDING-AN-AGENT-CAN-STILL-SEND-A-FULL-REFRESH-FROM-A-SCOPE-RECONCILE
    (seen on a fixture serve 2026-11-20): the readiness walk took 3-5 s after the
    record had landed in the watchdog's ``scope`` fingerprint, and a heartbeat in
    that gap reconciled it as an uncovered move — a full core for 2 of 4 adds.
    Here the projection stands in for that heartbeat: it reads the ``scope``
    family, which must not have moved yet, and the record must not exist yet.

    MUTATION: move the ``prepare_persona_updated`` call in ``AgentStore.save``
    below ``_write_model`` (project after the write) — this goes red.
    """

    from agent_runtime import paths
    from agent_runtime.state_patches import persona as persona_lane
    from agent_runtime.stream.fingerprint import FAMILY_SCOPE, scope_reading

    before = scope_reading(with_sessions=False).families[FAMILY_SCOPE]
    seen: list[tuple[bool, bool]] = []
    project = persona_lane.project_persona_wire_row

    def watching(persona):
        moved = scope_reading(with_sessions=False).families[FAMILY_SCOPE] != before
        seen.append((paths.agent_path(_COPY_ID).exists(), moved))
        return project(persona)

    monkeypatch.setattr(persona_lane, "project_persona_wire_row", watching)

    batch = _save_batch(_copy_persona())

    assert seen == [(False, False)], "the row is projected before the record lands"
    assert paths.agent_path(_COPY_ID).is_file()
    assert scope_reading(with_sessions=False).families[FAMILY_SCOPE] != before
    assert [event.type for event in batch] == [STATE_PATCHED_EVENT_TYPE, "persona.updated"]
    assert (batch[0].payload["op"], batch[0].payload["created"]) == (PATCH_OP_UPSERT, True)
