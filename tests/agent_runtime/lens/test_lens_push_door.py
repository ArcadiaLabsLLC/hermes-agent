"""Lens L3 — the push door (plan ``p10-agent-2026-10-19.md`` §5.4).

A source POSTs an alert or a JSON document to a route of an ENABLED monitor; the
route maps it onto the monitor's ``push`` feeds, the rules move, and an Episode
opens exactly as a poll would open it.

No serve is started: routes are written through the store / the method lane, the
mappings are driven as functions, and the listener (L3.3) runs on an ephemeral
loopback port and is stopped by each test. The home is the test's isolated
``HERMES_HOME``; the clock is fixed where a time matters.

Gates and their killing mutations (each red was recorded in the stage's commit):

* routes: a route may write a feed the poller reads — killed by dropping the
  ``not_a_push_feed`` check in ``ingress_routes._push_feed`` (the route registers);
  the poller never reads a ``push`` feed — killed by dropping the ``is_push_feed``
  skip in ``LensPoller.tick`` (one read, a ``push_only`` gap row); a revoked
  route's secret is forgotten — killed by dropping ``_forget`` from
  ``revoke_route`` (the credential is still set); no wire answer but register's
  carries the secret — killed by returning ``secret_ref`` resolved in
  ``public_route``.
"""

from __future__ import annotations

from datetime import datetime, UTC

import pytest

from agent_runtime.lens.store import LensStore, MonitorState

T0 = datetime(2026, 10, 19, 12, tzinfo=UTC)


def _monitor(*, feeds: list[dict] | None = None, rules: list[dict] | None = None) -> dict:
    alert = {"version": 1, "id": "alert", "kind": "push", "interval_ms": 60_000, "source": {}}
    return {"version": 1, "monitor_id": "pager", "feeds": feeds or [alert],
            "rules": rules if rules is not None else [
                {"version": 1, "id": "firing", "feed_id": "alert", "form": "threshold", "severity": "urgent",
                 "direction": "above", "threshold": 0.5, "recovery_threshold": 0.25, "window_ms": 0,
                 "samples": 1}],
            "automation": {"level": "notify", "when": "always", "daily_turn_cap": 4}, "persona_id": None}


def _enabled(manifest: dict | None = None) -> LensStore:
    manifest = manifest or _monitor()
    store = LensStore()
    store.create(manifest)
    store.seal(manifest["monitor_id"])
    store.set_state(manifest["monitor_id"], MonitorState.ENABLED)
    return store


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


# --- L3.1 routes ------------------------------------------------------------------


def test_a_route_registers_lists_and_revokes_on_the_method_lane():
    from agent_runtime.lens.credentials import credential_status, resolve_credential

    _enabled()
    registered = _rpc("runtime.lens.ingress.register", {"monitor_id": "pager", "kind": "alertmanager"})["result"]
    route_id, secret = registered["route_id"], registered["secret"]
    assert secret.startswith("whsec_")
    assert registered["url"] == f"http://127.0.0.1:47652/lens/{route_id}"
    assert registered["mapping"] == {"feed_id": "alert", "alerts": {}}
    assert resolve_credential(f"ingress:{route_id}").secret == secret

    listed = _rpc("runtime.lens.ingress.list", {"monitor_id": "pager"})["result"]["routes"]
    assert [row["route_id"] for row in listed] == [route_id]
    assert secret not in repr(listed) and secret not in repr(LensStore().routes())

    revoked = _rpc("runtime.lens.ingress.revoke", {"route_id": route_id})["result"]
    assert revoked["revoked"] is True
    assert credential_status(f"ingress:{route_id}")["set"] is False
    assert _rpc("runtime.lens.ingress.list", {})["result"]["routes"] == []
    missing = _rpc("runtime.lens.ingress.revoke", {"route_id": route_id})
    assert missing["error"]["data"]["reason"] == "route_not_found"


def test_a_route_never_writes_a_feed_the_poller_reads():
    polled = {"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
              "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}
    push = {"version": 1, "id": "alert", "kind": "push", "interval_ms": 60_000, "source": {}}
    _enabled(_monitor(feeds=[polled, push], rules=[]))

    refused = _rpc("runtime.lens.ingress.register",
                   {"monitor_id": "pager", "kind": "generic", "mapping": {"values": {"$.cpu": "api"}}})
    assert refused["error"]["data"] == {"reason": "invalid_value", "detail": "not_a_push_feed"}
    implied = _rpc("runtime.lens.ingress.register", {"monitor_id": "pager", "kind": "grafana"})
    assert implied["result"]["mapping"] == {"feed_id": "alert", "alerts": {}}
    ok = _rpc("runtime.lens.ingress.register",
              {"monitor_id": "pager", "kind": "generic", "mapping": {"values": {"$.firing": "alert"}}})
    assert ok["result"]["mapping"] == {"values": {"$.firing": "alert"}}


def test_two_push_feeds_need_a_named_mapping():
    pushes = [{"version": 1, "id": name, "kind": "push", "interval_ms": 60_000, "source": {}}
              for name in ("alert", "disk")]
    _enabled(_monitor(feeds=pushes, rules=[]))
    refused = _rpc("runtime.lens.ingress.register", {"monitor_id": "pager", "kind": "alertmanager"})
    assert refused["error"]["data"]["detail"] == "mapping_required"
    named = _rpc("runtime.lens.ingress.register",
                 {"monitor_id": "pager", "kind": "alertmanager",
                  "mapping": {"feed_id": "alert", "alerts": {"DiskFull": "disk"}}})
    assert named["result"]["mapping"] == {"feed_id": "alert", "alerts": {"DiskFull": "disk"}}


def test_an_unsealed_monitor_takes_no_route():
    LensStore().create(_monitor())
    refused = _rpc("runtime.lens.ingress.register", {"monitor_id": "pager", "kind": "alertmanager"})
    assert refused["error"]["data"]["reason"] == "not_sealed"


def test_the_poller_never_reads_a_push_feed():
    from agent_runtime.lens.poller import LensPoller

    store = _enabled()
    poller = LensPoller(store_factory=lambda: store, clock=lambda: T0)
    assert poller.catch_up() == 0
    assert poller.tick() == 0
    assert store.latest("pager", "alert") is None
