"""Lens W1 slice 3 — ``lens_propose_repair`` (plan ``planned/LENS_EXTENSIONS_2026-10-27.md`` §1
decision 7, row ``RT-LENS-SOURCE-REPAIR-PROPOSE``).

No real network: the preview read goes through an ``httpx.MockTransport`` and a fixed resolver.

Gates and their killing mutations (each red recorded in the row's commit):

* the stored draft differs from the sealed body only in the broken feed's ``source`` (two feeds,
  so a repair that touches every feed is seen) — killed by replacing the source of every feed;
* with no open ``source_broken`` Episode the tool is refused while an open one admits it (positive
  control) — killed by dropping the ``is_open`` check;
* a call that also carries ``rules`` is refused, and a pending draft is never written over.
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from test_lens_exit_door import T0

from agent_runtime.lens.episode import Decision, Episode, EpisodeState
from agent_runtime.lens.store import LensStore, LensStoreError, MonitorState, StoreRefusal
from agent_runtime.lens.tool import handle_lens_propose_repair, opening_block, propose_repair
from agent_runtime.lens.wire_value import WireError

PUBLIC = ["93.184.216.34"]
URL = "https://status.example.invalid"


def _feed(feed_id: str, selector: str) -> dict:
    return {"version": 1, "id": feed_id, "kind": "http_json", "interval_ms": 5000,
            "source": {"url": f"{URL}/{feed_id}", "selector": selector}}


def _monitor() -> dict:
    return {"version": 1, "monitor_id": "status", "feeds": [_feed("api", "$.cpu"), _feed("mem", "$.mem")],
            "rules": [{"version": 1, "id": "cpu_hot", "feed_id": "api", "form": "threshold", "severity": "urgent",
                       "direction": "above", "threshold": 90, "recovery_threshold": 80, "window_ms": 0,
                       "samples": 1}],
            "automation": {"level": "investigate", "when": "always", "daily_turn_cap": 4}, "persona_id": "qa"}


def _sealed() -> LensStore:
    store = LensStore()
    store.create(_monitor())
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)
    return store


def _broken(store: LensStore, **changes) -> Episode:
    episode = Episode(monitor_id="status", rule_id="source_broken:api", ordinal=1, first_seen=T0, last_seen=T0,
                      count=1, state=EpisodeState.ACTIVE)
    episode = replace(episode, **changes)
    store.save_episode(episode)
    return episode


def _client(body: dict) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
                        follow_redirects=False)


def _repair(store: LensStore, body: dict | None = None, **extra) -> dict:
    args = {"monitor_id": "status", "feed_id": "api", "source": {"url": f"{URL}/api/v2", "selector": "$.cpu_pct"},
            **extra}
    return propose_repair(args, store=store, client=_client(body or {"cpu_pct": 42}), resolver=lambda host: PUBLIC)


def test_the_draft_differs_from_the_sealed_revision_only_in_the_broken_feeds_source():
    store = _sealed()
    _broken(store)

    answer = _repair(store)

    assert answer["preview"]["number"] == 42.0 and answer["sealed"] is False
    monitor = store.get("status")
    sealed, draft = monitor["sealed"]["manifest"], monitor["draft"]
    assert draft["feeds"][0]["source"] == {"url": f"{URL}/api/v2", "selector": "$.cpu_pct"}
    assert {**draft, "feeds": [{**draft["feeds"][0], "source": sealed["feeds"][0]["source"]}, *draft["feeds"][1:]]} \
        == sealed, "rules, automation and the other feed are byte-identical"
    assert monitor["sealed"]["revision"] == 1 and monitor["state"] == "enabled", "never sealed by the persona"
    assert store.seal("status")["sealed"]["revision"] == 2, "the operator's seal makes it the next revision"


def test_only_an_open_source_broken_episode_admits_a_repair():
    store = _sealed()
    with pytest.raises(LensStoreError) as refused:
        _repair(store)
    assert refused.value.code is StoreRefusal.SOURCE_NOT_BROKEN
    episode = _broken(store, state=EpisodeState.RECOVERED, decision=Decision.DISMISS, decided_at=T0)
    with pytest.raises(LensStoreError):
        _repair(store)
    store.save_episode(replace(episode, decision=None, decided_at=None))
    assert _repair(store)["feed_id"] == "api", "positive control: an unsettled open Episode admits it"
    assert store.get("status")["draft"] is not None


def test_a_repair_cannot_carry_rules_or_write_over_a_pending_draft_or_store_a_dead_source():
    store = _sealed()
    _broken(store)
    with pytest.raises(WireError):
        _repair(store, rules=[])
    with pytest.raises(WireError):
        _repair(store, body={"cpu": 42})
    assert store.get("status")["draft"] is None, "a source that answers no value is never drafted"
    assert json.loads(handle_lens_propose_repair({"monitor_id": "status", "feed_id": "disk", "source": {}})) \
        == {"error": "invalid_value", "detail": "feed_id"}

    store.create(_monitor())
    with pytest.raises(LensStoreError) as refused:
        _repair(store)
    assert refused.value.code is StoreRefusal.DRAFT_PENDING
    assert store.get("status")["draft"] == store.get("status")["sealed"]["manifest"], "the operator's draft stands"


def test_the_source_broken_opening_block_names_the_repair_tool(tmp_path):
    from datetime import timedelta

    from agent_runtime.lens.evidence import build_evidence

    store = _sealed()
    episode = _broken(store)
    evidence = build_evidence((), monitor_id="status", feed_ids=["api"], start=T0 - timedelta(minutes=5), end=T0)
    block = opening_block(store.get("status")["sealed"]["manifest"], episode, evidence, tmp_path)
    assert "lens_propose_repair" in block
