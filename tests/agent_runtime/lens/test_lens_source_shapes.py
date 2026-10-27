"""Lens W1 slice 1 — source shapes, the known-good skeleton, observation provenance and broken
detection (plan ``planned/LENS_EXTENSIONS_2026-10-27.md`` §1 decisions 1–4, ``RT-LENS-SOURCE-REPAIR``).

No real network: reads go through an ``httpx.MockTransport`` and a fixed resolver, the poller is
driven by ``tick`` on a fake clock.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, UTC

import httpx

from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.shapes import (
    BROKEN_AFTER_READS, MAXIMUM_SKELETON_BYTES, SHAPE_REASONS, canonical_skeleton, fingerprint, json_skeleton,
    prometheus_skeleton, source_broken, sql_skeleton,
)
from agent_runtime.lens.sources.transport import ReadReason
from agent_runtime.lens.store import LensStore, MonitorState
from agent_runtime.lens.store_shapes import feed_broken, feed_shape

T0 = datetime(2026, 10, 27, 12, tzinfo=UTC)
PUBLIC = ["93.184.216.34"]


# --- decision 1: the skeleton carries no value ------------------------------------


def test_the_same_document_with_other_values_has_the_same_fingerprint():
    one = {"cpu": 12.5, "host": {"name": "a", "tags": ["x", "y"]}, "ok": True}
    two = {"cpu": 99.0, "host": {"name": "zzz", "tags": ["q"]}, "ok": False}
    assert fingerprint(json_skeleton(one)) == fingerprint(json_skeleton(two))


def test_a_renamed_key_changes_the_fingerprint():
    one = {"cpu": 12.5, "host": {"name": "a"}}
    renamed = {"cpu_pct": 12.5, "host": {"name": "a"}}
    retyped = {"cpu": "12.5", "host": {"name": "a"}}
    assert fingerprint(json_skeleton(one)) != fingerprint(json_skeleton(renamed))
    assert fingerprint(json_skeleton(one)) != fingerprint(json_skeleton(retyped))


def test_no_value_reaches_the_canonical_skeleton():
    canonical = canonical_skeleton(json_skeleton({"token": "s3cret-value", "n": 424242}))
    assert "s3cret-value" not in canonical and "424242" not in canonical
    assert canonical == '[["$","object"],["$.n","number"],["$.token","string"]]'


def test_a_huge_document_is_bounded():
    wide = {f"key_{i}": {"inner": i} for i in range(5000)}
    deep: dict = {}
    node = deep
    for _ in range(40):
        node["d"] = {}
        node = node["d"]
    assert len(json_skeleton(wide)) == 256
    assert len(canonical_skeleton(json_skeleton(wide))) <= MAXIMUM_SKELETON_BYTES
    assert max(len(path) for path, _ in json_skeleton(deep)) == len("$" + ".d" * 8)


def test_prometheus_and_sql_skeletons_carry_names_never_values():
    answer = {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"job": "api", "instance": "10.0.0.1:9100"}, "value": [1, "0.5"]}]}}
    moved = {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"job": "web", "instance": "10.9.9.9:9100"}, "value": [2, "7"]}]}}
    relabelled = {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"job": "api", "pod": "x"}, "value": [1, "0.5"]}]}}
    assert prometheus_skeleton(answer) == (("resultType", "vector"), ("series", "instance,job"))
    assert fingerprint(prometheus_skeleton(answer)) == fingerprint(prometheus_skeleton(moved))
    assert fingerprint(prometheus_skeleton(answer)) != fingerprint(prometheus_skeleton(relabelled))
    assert sql_skeleton(["total"], (42,)) == (("column.total", "integer"),)
    assert sql_skeleton(["total"], None) == (("column.total", "null"),)


def test_every_shape_reason_is_a_read_reason_and_no_transport_reason_is_one():
    reasons = {reason.value for reason in ReadReason}
    assert SHAPE_REASONS <= reasons
    assert not SHAPE_REASONS & {"timeout", "network", "http_status", "redirect_refused", "too_large",
                                "private_address_refused", "credential_missing"}


# --- decision 3: broken detection, pure -------------------------------------------


def test_three_shape_reason_reads_are_broken_and_two_are_not():
    assert not source_broken(["ok", "selector_missing", "selector_missing"], latest_fingerprint=None,
                             known_good_fingerprint=None)
    assert source_broken(["selector_missing"] * BROKEN_AFTER_READS, latest_fingerprint=None,
                         known_good_fingerprint=None)


def test_three_timeouts_are_never_broken():
    """Positive control for the typed set: the same count of transport failures is not drift."""

    assert not source_broken(["timeout"] * 3, latest_fingerprint="other", known_good_fingerprint="good")
    assert not source_broken(["selector_missing", "selector_missing", "timeout"], latest_fingerprint="other",
                             known_good_fingerprint="good")


def test_one_shape_read_off_the_known_good_fingerprint_is_broken_on_the_first_read():
    assert source_broken(["ok", "selector_missing"], latest_fingerprint="drifted", known_good_fingerprint="good")
    # The same reason over the KNOWN-GOOD shape is not drift yet (a value can be absent in a good shape).
    assert not source_broken(["ok", "not_a_number"], latest_fingerprint="good", known_good_fingerprint="good")


# --- decisions 1, 3, 4 through the poller -----------------------------------------


def _manifest() -> dict:
    return {"version": 1, "monitor_id": "status", "rules": [], "persona_id": None,
            "feeds": [{"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
                       "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}],
            "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}}


def _poller(store: LensStore, bodies: list) -> tuple[LensPoller, list]:
    at = [T0]
    answers = iter(bodies)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=next(answers))),
                          follow_redirects=False)
    return LensPoller(store_factory=lambda: store, clock=lambda: at[0], client=client,
                      resolver=lambda host: PUBLIC), at


def _enabled() -> LensStore:
    store = LensStore()
    store.create(_manifest())
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)
    return store


def test_a_renamed_key_marks_the_feed_broken_on_its_first_bad_read_and_keeps_both_skeletons():
    store = _enabled()
    poller, at = _poller(store, [{"cpu": 10, "host": "a"}, {"cpu": 20, "host": "b"}, {"cpu_pct": 30, "host": "c"}])
    for _ in range(3):
        poller.tick()
        if at[0] == T0 + timedelta(seconds=5):
            assert not feed_broken(store, "status", "api"), "two good reads are not broken"
        at[0] += timedelta(seconds=5)

    shape = feed_shape(store, "status", "api")
    assert shape["good_fingerprint"] == fingerprint(json_skeleton({"cpu": 0, "host": ""}))
    assert shape["other_fingerprint"] == shape["last_fingerprint"] == fingerprint(
        json_skeleton({"cpu_pct": 0, "host": ""}))
    assert "cpu_pct" in shape["other_skeleton"] and "30" not in shape["other_skeleton"]
    assert feed_broken(store, "status", "api")


def test_a_good_read_after_drift_heals_and_keeps_the_drifted_skeleton_on_record():
    store = _enabled()
    poller, at = _poller(store, [{"cpu": 1}, {"cpu_pct": 2}, {"cpu": 3}])
    for _ in range(3):
        poller.tick()
        at[0] += timedelta(seconds=5)
    shape = feed_shape(store, "status", "api")
    assert shape["last_fingerprint"] == shape["good_fingerprint"] and not feed_broken(store, "status", "api")
    assert shape["other_fingerprint"] == fingerprint(json_skeleton({"cpu_pct": 0}))


def test_observations_carry_the_sealed_revision_that_read_them():
    store = _enabled()
    poller, _ = _poller(store, [{"cpu": 1}])
    poller.tick()
    store.record("status", "api", observed_at=T0, received_at=T0, value=None, reason="watcher_offline")
    with store.connection() as conn:
        revisions = [row[0] for row in conn.execute("SELECT revision FROM observations ORDER BY sequence")]
    assert revisions == [1, 1]


def test_a_store_written_before_the_revision_column_gains_it(tmp_path):
    path = tmp_path / "lens.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE observations (monitor_id TEXT NOT NULL, feed_id TEXT NOT NULL, sequence INTEGER "
                 "NOT NULL, observed_ms INTEGER NOT NULL, received_ms INTEGER NOT NULL, value REAL, reason TEXT "
                 "NOT NULL, http_status INTEGER, PRIMARY KEY (monitor_id, feed_id, sequence))")
    conn.execute("INSERT INTO observations VALUES ('m', 'f', 7, 0, 0, 1.0, 'ok', NULL)")
    conn.commit()
    conn.close()

    store = LensStore(path)
    store.record("m", "f", observed_at=T0, received_at=T0, value=2.0, reason="ok")
    assert [row["value"] for row in store.observations("m", "f", start=T0 - timedelta(days=30000),
                                                        end=T0 + timedelta(days=1))] == [1.0, 2.0]
