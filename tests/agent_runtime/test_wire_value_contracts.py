"""The wire value contracts (``docs/agent-runtime-harness/03-transport-and-wire.md``
§ 11, owner rulings 2026-10-15): what a value on the wire MEANS, so the
launcher's readers stop answering the same fact differently.

Each test proves the producer half of one ruling by building the real thing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_runtime.stream import hydrate_frame

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "stream_frames"

#: Keys whose value is an integer by name. Over-approximates on purpose: a key
#: this matches that legitimately carries a non-integer is a finding, not noise.
INTEGER_KEY = re.compile(r"(_ms|_count|_seq|_offset|_bytes|_code|^revision|^offset|^generation)$")


def _integer_fields(obj, path: str = ""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            where = f"{path}/{key}"
            if isinstance(key, str) and INTEGER_KEY.search(key) and value is not None and not isinstance(value, (dict, list)):
                yield where, value
            yield from _integer_fields(value, where)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _integer_fields(value, f"{path}[{index}]")


def _not_integers(obj) -> tuple[int, list[tuple[str, object]]]:
    fields = list(_integer_fields(obj))
    bad = [(where, value) for where, value in fields if isinstance(value, bool) or not isinstance(value, int)]
    return len(fields), bad


@pytest.fixture(autouse=True)
def _reset_core_cache_lane():
    from tests._downstream import _seams

    _seams.reset_core_cache_process_state()
    yield
    _seams.reset_core_cache_process_state()


# ── RT-WIRE-FACT-DECODES-DIFFERENT: strict integers on the wire ─────────────


def test_a_built_hydrate_frame_carries_every_integer_as_a_json_integer():
    """No numeric string, no float, no bool where an integer is meant: a reader
    may refuse anything else, so the producer must never send it."""

    seen, bad = _not_integers(json.loads(json.dumps(hydrate_frame(), default=str)))
    assert seen > 10, "the walk found almost no integer fields; the key pattern drifted"
    assert bad == []


def test_every_committed_stream_golden_carries_every_integer_as_a_json_integer():
    seen_total = 0
    offenders: list[tuple[str, str, object]] = []
    for path in sorted(FIXTURES.glob("*.json")):
        seen, bad = _not_integers(json.loads(path.read_text(encoding="utf-8")))
        seen_total += seen
        offenders.extend((path.name, where, value) for where, value in bad)
    assert seen_total > 100
    assert offenders == []


# ── RT-TWO-RESOLVERS-ANSWER-HARNESS: an empty realm-adopt reply is a failure ─


def test_a_successful_realm_adopt_never_answers_empty(monkeypatch):
    """Success is a non-empty list envelope even when nothing was adopted, so a
    reader may treat an empty or null reply as a failure."""

    from agent_runtime import realm_membership, realm_verbs

    monkeypatch.setattr(realm_membership, "adopt_realms", lambda *_a, **_k: [])
    data = realm_verbs.realm_adopt(object(), dry_run=True)

    assert isinstance(data, dict) and data
    assert data["kind"] == "list"
    assert data["item_kind"] == "realm"
    assert data["count"] == 0
