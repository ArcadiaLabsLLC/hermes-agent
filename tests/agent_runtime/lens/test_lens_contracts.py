"""Lens L0 — the contract gates the plan names (``eternia-lens-in-hermes.md`` §5 L0).

* A manifest with one unknown key is REFUSED (closed schema, every level).
* A rule "over 90 for 5 min" does NOT fire on a 4-minute breach.

Plus the wire floor (duplicate key, non-finite, over budget), the seal's digest
check, and ``runtime.lens.list`` on the method lane.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone, UTC

import pytest

from agent_runtime.lens.feed import Observation
from agent_runtime.lens.manifest import decode_manifest, read_manifest
from agent_runtime.lens.rules import Verdict, evaluate, read_rule
from agent_runtime.lens.seal import seal_manifest
from agent_runtime.lens.wire_value import WireError, WireRefusal, canonical_json, decode_strict_json

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def _manifest() -> dict:
    return {
        "version": 1,
        "monitor_id": "api-health",
        "feeds": [{
            "version": 1, "id": "cpu", "kind": "prometheus", "interval_ms": 60000,
            "source": {"base_url": "https://prom.example.invalid", "query": "avg(rate(cpu[5m]))"},
        }],
        "rules": [{
            "version": 1, "id": "hot", "feed_id": "cpu", "form": "for_duration", "severity": "urgent",
            "direction": "above", "threshold": 90, "recovery_threshold": 80, "window_ms": 300000, "samples": 1,
        }],
        "automation": {"level": "investigate", "when": "urgent", "daily_turn_cap": 4},
        "persona_id": "analyst",
    }


def test_a_valid_manifest_reads_and_round_trips():
    manifest = read_manifest(_manifest())
    assert read_manifest(manifest) == manifest
    assert decode_manifest(canonical_json(manifest)) == manifest


@pytest.mark.parametrize("path", [(), ("feeds", 0), ("feeds", 0, "source"), ("rules", 0), ("automation",)])
def test_one_unknown_key_anywhere_is_refused(path):
    doc = _manifest()
    target = doc
    for step in path:
        target = target[step]
    target["surprise"] = 1
    with pytest.raises(WireError) as caught:
        read_manifest(doc)
    assert caught.value.code is WireRefusal.UNKNOWN_KEY


@pytest.mark.parametrize("mutate, code", [
    (lambda d: d["automation"].update(level="act"), WireRefusal.UNKNOWN_ENUM),  # ruling 3: no act level
    (lambda d: d["feeds"][0].update(kind="sql_readonly"), WireRefusal.INVALID_VALUE),  # L4, not built
    (lambda d: d["rules"][0].update(feed_id="nope"), WireRefusal.INVALID_VALUE),
    (lambda d: d["rules"][0].update(recovery_threshold=95), WireRefusal.INVALID_VALUE),  # no hysteresis
    (lambda d: d["feeds"][0]["source"].update(base_url="https://u:p@prom.example.invalid"), WireRefusal.INVALID_STRING),
    (lambda d: d.pop("persona_id"), WireRefusal.MISSING_KEY),
])
def test_the_closed_schema_refuses_typed(mutate, code):
    doc = _manifest()
    mutate(doc)
    with pytest.raises(WireError) as caught:
        read_manifest(doc)
    assert caught.value.code is code


@pytest.mark.parametrize("source, code", [
    ('{"a":1,"a":2}', WireRefusal.DUPLICATE_KEY),
    ('{"a":NaN}', WireRefusal.NON_FINITE),
    ('{"a":Infinity}', WireRefusal.NON_FINITE),
    ('{"a":', WireRefusal.INVALID_JSON),
    ("[" * 30 + "]" * 30, WireRefusal.OVER_BUDGET),
])
def test_the_strict_decoder_refuses_what_json_loads_accepts(source, code):
    with pytest.raises(WireError) as caught:
        decode_strict_json(source)
    assert caught.value.code is code


def _minutely(values: list[float]) -> list[Observation]:
    start = NOW - timedelta(minutes=len(values) - 1)
    return [
        Observation(monitor_id="api-health", feed_id="cpu", sequence=i + 1, observed_at=start + timedelta(minutes=i),
                    received_at=start + timedelta(minutes=i), value=v)
        for i, v in enumerate(values)
    ]


def _verdict(values: list[float]) -> Verdict:
    rule = read_rule(_manifest()["rules"][0])
    return evaluate(rule, _minutely(values), now=NOW, expected_interval=timedelta(minutes=1), was_firing=False)


def test_a_four_minute_breach_does_not_fire_a_five_minute_rule():
    # Over 90 from t-4m to t (five samples, four minutes); the t-5m anchor is 50.
    assert _verdict([50, 50, 95, 95, 95, 95, 95]) is Verdict.HEALTHY
    # Only four minutes of history at all: the window is incomplete, so unknown.
    assert _verdict([95, 95, 95, 95, 95]) is Verdict.UNKNOWN


def test_a_five_minute_breach_fires_it():
    assert _verdict([95, 95, 95, 95, 95, 95]) is Verdict.FIRING


def test_a_seal_names_its_bytes_and_refuses_changed_ones():
    sealed = seal_manifest(_manifest(), revision=1)
    assert sealed.manifest() == read_manifest(_manifest())
    tampered = copy.copy(sealed)
    object.__setattr__(tampered, "body", sealed.body.replace(b"90", b"99"))
    with pytest.raises(WireError) as caught:
        tampered.manifest()
    assert caught.value.code is WireRefusal.INVALID_DIGEST


def test_runtime_lens_list_is_on_the_method_lane():
    from agent_runtime import serve_rpc
    from agent_runtime.call_authorization import TIER_CONSOLE

    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": "runtime.lens.list", "params": {}})
    assert reply["result"]["feed_kinds"] == {
        "http_json": "available", "prometheus": "available",
        "sql_readonly": "unavailable", "command_allowlisted": "unavailable",
    }
    assert serve_rpc.method_tier("runtime.lens.list") == TIER_CONSOLE
