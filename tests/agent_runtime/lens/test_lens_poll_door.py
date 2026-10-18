"""Lens L1 — the poll door (plan ``eternia-lens-in-hermes.md`` §5 L1).

The gates the plan names:

* a feed that fails three polls records THREE gaps (a failed read is never silence);
* raw rows older than 24 h do not survive a retention pass (and are folded first);
* a resolved credential value appears in NO stored row and NO read surface
  (launcher plan MONITORING_CREDENTIALS_SEPARATION S2 — every evidence path).

No real network: every read goes through an ``httpx.MockTransport`` and a fixed
resolver; no serve is started (the poller is driven by ``tick`` on a fake clock).
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

import httpx
import pytest

from agent_runtime.lens.credentials import credential_status, resolve_credential, set_credential
from agent_runtime.lens.evidence import build_evidence
from agent_runtime.lens.feed import Observation
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.retention import apply_retention
from agent_runtime.lens.sources import read_feed_source
from agent_runtime.lens.store import LensStore, MonitorState, from_ms

CORPUS = Path(__file__).with_name("conformance")
T0 = datetime(2026, 10, 16, 12, tzinfo=UTC)
PUBLIC = ["93.184.216.34"]


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta) -> None:
        self.at += timedelta(**delta)


def _feed(**extra) -> dict:
    return {"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
            "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}, **extra}


def _manifest(feed: dict | None = None, rules: list | None = None) -> dict:
    return {"version": 1, "monitor_id": "status", "feeds": [feed or _feed()], "rules": rules or [],
            "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}, "persona_id": None}


def _enabled_store(manifest: dict) -> LensStore:
    store = LensStore()
    store.create(manifest)
    store.seal(manifest["monitor_id"])
    store.set_state(manifest["monitor_id"], MonitorState.ENABLED)
    return store


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _rows(store: LensStore, feed_id: str = "api") -> list[dict]:
    return store.observations("status", feed_id, start=T0 - timedelta(days=30), end=T0 + timedelta(days=30))


# --- gate 1: a failed poll is a recorded gap ------------------------------------


def test_three_failed_polls_record_three_gaps():
    store = _enabled_store(_manifest())
    clock = _Clock(T0)
    poller = LensPoller(clock=clock, client=_client(lambda request: httpx.Response(503)),
                        resolver=lambda host: PUBLIC)
    reads = 0
    for _ in range(40):  # 40 s of ticks: backoff spaces the reads, it never drops them
        reads += poller.tick()
        clock.advance(seconds=1)
        if reads == 3:
            break

    rows = _rows(store)
    assert [(row["gap"], row["reason"], row["http_status"]) for row in rows] == [(True, "http_status", 503)] * 3
    assert [row["sequence"] for row in rows] == [1, 2, 3]
    gaps = [r["observed_ms"] for r in rows]
    assert gaps[1] - gaps[0] == 5000 and gaps[2] - gaps[1] == 10000  # backed off x2 after the second failure


def test_an_answering_feed_records_numbers_and_a_threshold_rule_opens_an_episode():
    rule = {"version": 1, "id": "hot", "feed_id": "api", "form": "threshold", "severity": "urgent",
            "direction": "above", "threshold": 90, "recovery_threshold": 80, "window_ms": 0, "samples": 1}
    store = _enabled_store(_manifest(rules=[rule]))
    clock = _Clock(T0)
    values = iter([50, 95])
    poller = LensPoller(clock=clock, client=_client(lambda r: httpx.Response(200, json={"cpu": next(values)})),
                        resolver=lambda host: PUBLIC)
    poller.tick()
    clock.advance(seconds=5)
    poller.tick()

    assert [row["value"] for row in _rows(store)] == [50.0, 95.0]
    episodes = store.episodes(monitor_id="status")
    assert [(e["rule_id"], e["state"], e["ordinal"], e["count"]) for e in episodes] == [("hot", "active", 1, 1)]


def test_a_feed_the_watcher_missed_gets_one_offline_gap_at_start():
    store = _enabled_store(_manifest())
    store.record("status", "api", observed_at=T0, received_at=T0, value=1.0, reason="ok")
    poller = LensPoller(clock=_Clock(T0 + timedelta(hours=2)), resolver=lambda host: PUBLIC)

    assert poller.catch_up() == 1
    assert [(row["gap"], row["reason"]) for row in _rows(store)][-1] == (True, "watcher_offline")


# --- gate 2: retention ------------------------------------------------------------


def test_raw_rows_older_than_a_day_are_folded_into_rollups_then_removed():
    store = LensStore()
    store.create(_manifest())
    old = T0 - timedelta(hours=25)
    for i, value in enumerate([10.0, None, 30.0]):
        store.record("status", "api", observed_at=old + timedelta(seconds=10 * i), received_at=old,
                     value=value, reason="ok" if value is not None else "timeout")
    store.record("status", "api", observed_at=T0, received_at=T0, value=99.0, reason="ok")

    receipt = apply_retention(store, T0)

    assert receipt.raw_folded == 3
    assert [row["value"] for row in _rows(store)] == [99.0]
    [rollup] = store.rollups("status", "api")
    assert (rollup["samples"], rollup["gaps"], rollup["min"], rollup["max"], rollup["sum"]) == (2, 1, 10.0, 30.0, 40.0)
    assert apply_retention(store, T0).raw_folded == 0  # idempotent
    # Sequences are never reused after a fold.
    assert store.record("status", "api", observed_at=T0, received_at=T0, value=1.0, reason="ok").sequence == 5


def test_rollups_older_than_seven_days_are_removed():
    store = LensStore()
    store.create(_manifest())
    store.record("status", "api", observed_at=T0 - timedelta(days=8), received_at=T0, value=1.0, reason="ok")
    apply_retention(store, T0 - timedelta(days=6))  # folds it while the rollup is young
    assert len(store.rollups("status", "api")) == 1
    assert apply_retention(store, T0).rollups_deleted == 1
    assert store.rollups("status", "api") == []


# --- gate 3: credentials --------------------------------------------------------


SECRET = "do-not-copy-this-secret"


def _secret_forms() -> list[str]:
    return [SECRET, base64.b64encode(SECRET.encode()).decode()]


def _redaction_case() -> dict:
    pins = json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))["files"]
    raw = (CORPUS / "http_redaction_corpus.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == pins["http_redaction_corpus.json"]
    [case] = json.loads(raw)
    return case


def _surfaces(store: LensStore) -> str:
    """Every read surface Lens offers, as one string."""

    from agent_runtime import serve_rpc

    replies = [serve_rpc.handle_request({"jsonrpc": "2.0", "id": i, "method": m, "params": p}) for i, (m, p) in
               enumerate([
                   ("runtime.lens.list", {}),
                   ("runtime.lens.get", {"monitor_id": "status"}),
                   ("runtime.lens.latest", {"monitor_id": "status"}),
                   ("runtime.lens.range", {"monitor_id": "status", "feed_id": "api",
                                           "start_ms": int((T0 - timedelta(days=1)).timestamp() * 1000),
                                           "end_ms": int((T0 + timedelta(days=1)).timestamp() * 1000)}),
                   ("runtime.lens.episodes", {}),
                   ("runtime.lens.fold", {}),
               ])]
    assert all("result" in reply for reply in replies), replies
    observations = [Observation(monitor_id="status", feed_id="api", sequence=r["sequence"],
                                observed_at=from_ms(r["observed_ms"]), received_at=from_ms(r["received_ms"]),
                                value=r["value"], gap=r["gap"]) for r in _rows(store)]
    window = build_evidence(observations, monitor_id="status", feed_ids=["api"],
                            start=T0 - timedelta(days=1), end=T0 + timedelta(days=1))
    return json.dumps(replies) + window.canonical_bytes.decode()


def test_a_resolved_credential_reaches_the_request_and_no_stored_row_or_read_surface():
    case = _redaction_case()
    set_credential("status-token", scheme="bearer", secret=SECRET, now=T0)
    store = _enabled_store(_manifest(_feed(credential_ref="status-token")))
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        if len(seen) == 1:  # the corpus's 401 echoing the secret, plain and encoded
            return httpx.Response(case["httpStatus"], json=case["body"])
        return httpx.Response(200, json={"cpu": 42, "echo": SECRET, "auth": request.headers["authorization"]})

    clock = _Clock(T0)
    poller = LensPoller(clock=clock, client=_client(handler), resolver=lambda host: PUBLIC)
    poller.tick()
    first = _rows(store)[-1]
    assert {"status": "unavailable" if first["gap"] else "available", "number": first["value"],
            "httpStatus": first["http_status"]} == {**case["oracle"]}
    clock.advance(seconds=5)
    poller.tick()

    assert seen == [f"Bearer {SECRET}"] * 2
    assert _rows(store)[-1]["value"] == 42.0
    stored = b"".join(path.read_bytes() for path in store.path.parent.glob("lens.sqlite3*"))
    surfaces = _surfaces(store)
    for form in _secret_forms():
        assert form.encode() not in stored
        assert form not in surfaces
    assert credential_status("status-token") == {"ref": "status-token", "set": True,
                                                 "rotated_at": "2026-10-16T12:00:00.000Z"}


def test_a_reference_this_home_does_not_hold_is_a_gap_and_no_request(monkeypatch, tmp_path):
    set_credential("status-token", scheme="bearer", secret=SECRET)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "other-persona-home"))
    assert resolve_credential("status-token") is None  # another home's row is not this home's

    calls = []
    result = read_feed_source(_feed(credential_ref="status-token"),
                              client=_client(lambda r: calls.append(r) or httpx.Response(200, json={"cpu": 1})),
                              resolver=lambda host: PUBLIC)
    assert (result.value, result.reason.value, calls) == (None, "credential_missing", [])


def test_basic_credentials_send_the_pair_and_the_status_never_carries_the_value():
    status = set_credential("db", scheme="basic", secret=SECRET, username="watcher")
    assert SECRET not in json.dumps(status)
    headers = resolve_credential("db").headers()
    assert headers["Authorization"] == "Basic " + base64.b64encode(f"watcher:{SECRET}".encode()).decode()
    assert SECRET not in repr(resolve_credential("db"))


# --- the source edge --------------------------------------------------------------


@pytest.mark.parametrize("address, opted_in, reason", [
    ("127.0.0.1", False, "private_address_refused"),
    ("10.1.2.3", False, "private_address_refused"),
    ("169.254.169.254", False, "private_address_refused"),
    ("127.0.0.1", True, "ok"),
])
def test_private_addresses_need_the_feed_to_opt_in(address, opted_in, reason):
    feed = _feed(**({"allow_private_network": True} if opted_in else {}))
    result = read_feed_source(feed, client=_client(lambda r: httpx.Response(200, json={"cpu": 1})),
                              resolver=lambda host: [address])
    assert result.reason.value == reason


def test_a_redirect_is_never_followed():
    result = read_feed_source(_feed(), client=_client(
        lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1/"})), resolver=lambda host: PUBLIC)
    assert (result.value, result.reason.value, result.http_status) == (None, "redirect_refused", 302)


@pytest.mark.parametrize("data, outcome", [
    ({"resultType": "scalar", "result": [1.7e9, "0.5"]}, (0.5, "ok")),
    ({"resultType": "vector", "result": [{"metric": {}, "value": [1.7e9, "91"]}]}, (91.0, "ok")),
    ({"resultType": "vector", "result": []}, (None, "no_series")),
    ({"resultType": "vector", "result": [{"value": [1, "1"]}, {"value": [1, "2"]}]}, (None, "ambiguous_series")),
    ({"resultType": "vector", "result": [{"value": [1, "NaN"]}]}, (None, "not_a_number")),
])
def test_prometheus_instant_query_shapes(data, outcome):
    feed = {"version": 1, "id": "cpu", "kind": "prometheus", "interval_ms": 60000,
            "source": {"base_url": "https://prom.example.invalid", "query": "up"}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/query" and request.url.params["query"] == "up"
        return httpx.Response(200, json={"status": "success", "data": data})

    result = read_feed_source(feed, client=_client(handler), resolver=lambda host: PUBLIC)
    assert (result.value, result.reason.value) == outcome


# --- the method lane --------------------------------------------------------------


def _call(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def test_the_lifecycle_verbs_draft_seal_enable_pause_retire():
    assert _call("runtime.lens.create", {"manifest": _manifest()})["result"]["state"] == "draft"
    refused = _call("runtime.lens.enable", {"monitor_id": "status"})
    assert refused["error"]["data"]["reason"] == "not_sealed"
    sealed = _call("runtime.lens.seal", {"monitor_id": "status"})["result"]
    assert sealed["sealed"]["revision"] == 1 and sealed["draft"] is None
    assert _call("runtime.lens.enable", {"monitor_id": "status"})["result"]["state"] == "enabled"
    assert _call("runtime.lens.pause", {"monitor_id": "status"})["result"]["state"] == "paused"
    assert _call("runtime.lens.retire", {"monitor_id": "status"})["result"]["state"] == "retired"
    assert _call("runtime.lens.create", {"manifest": _manifest()})["error"]["data"]["reason"] == "monitor_retired"
    assert _call("runtime.lens.get", {"monitor_id": "nope"})["error"]["data"]["reason"] == "monitor_not_found"
    bad = _manifest()
    bad["feeds"][0]["surprise"] = True
    assert _call("runtime.lens.create", {"manifest": bad})["error"]["data"] == {"reason": "unknown_key",
                                                                               "detail": "surprise"}


def test_preview_reads_and_writes_nothing():
    reply = _call("runtime.lens.preview", {"manifest": _manifest(_feed(credential_ref="absent"))})
    assert reply["result"]["feeds"] == [{"feed_id": "api", "status": "unavailable", "number": None,
                                         "reason": "credential_missing", "http_status": None}]
    assert not LensStore().exists()


@pytest.mark.parametrize("extra, number, reason", [
    ({"value_type": {"kind": "count"}}, 2.5, "type_mismatch"),
    ({"plausible": {"minimum": 1, "maximum": 100}}, 0.0, "implausible"),
    ({"plausible": {"minimum": 1, "maximum": 100}}, 42.0, "ok"),
])
def test_preview_shows_the_value_the_poller_would_store(monkeypatch, extra, number, reason):
    from agent_runtime.lens import sources
    from agent_runtime.lens.feed import FeedKind
    from agent_runtime.lens.sources.transport import ReadReason, ReadResult

    monkeypatch.setitem(sources.SOURCE_READERS, FeedKind.HTTP_JSON,
                        lambda feed, **kw: ReadResult(value=number, reason=ReadReason.OK, http_status=200))
    [feed] = _call("runtime.lens.preview", {"manifest": _manifest(_feed(**extra))})["result"]["feeds"]
    stored = None if reason != "ok" else number
    assert (feed["number"], feed["reason"], feed["status"]) == (
        stored, reason, "available" if stored is not None else "unavailable")
    assert not LensStore().exists()


def test_the_fold_of_a_home_without_lens_is_empty_and_creates_no_store():
    fold = _call("runtime.lens.fold", {})["result"]
    assert (fold["monitors_enabled"], fold["open_episodes"], fold["latest"], fold["last_receipt"]) == (0, [], [], None)
    assert not LensStore().exists()


def test_credential_set_is_write_only():
    reply = _call("runtime.lens.credential.set", {"ref": "k", "scheme": "bearer", "secret": SECRET})
    assert reply["result"]["set"] is True and SECRET not in json.dumps(reply)
    assert _call("runtime.lens.credential.set", {"ref": "k", "scheme": "bearer", "secret": SECRET,
                                                "value": 1})["error"]["data"]["reason"] == "unknown_key"
