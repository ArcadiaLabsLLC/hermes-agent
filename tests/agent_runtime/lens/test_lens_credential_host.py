"""RT-LENS-CREDENTIAL-NOT-BOUND-TO-A-HOST — a sign-in is only ever sent to the address it was saved for.

The defect, reproduced through the entry Eternia uses (``runtime.lens.preview``): a credential
was found by its ``credential_ref`` name alone, so any manifest naming a ref this PC holds (a
persona's proposal the operator previews, an edited source address) sent that secret to a host
its owner never chose.

The fix lives where the fact lives: the credential file records the address a secret is for
(``lens.credentials``), ``runtime.lens.credential.set`` reads that address off the monitors that
name the ref (never off the request), and the ONE resolver refuses a read to any other address
with a typed gap.

No real network: every read goes through an ``httpx.MockTransport`` and a fixed resolver.
"""

from __future__ import annotations

import json

import httpx
import pytest

from agent_runtime.lens.credentials import (
    CredentialRefusal,
    credential_host,
    credential_status,
    credentials_path,
    resolve_credential,
    set_credential,
)
from agent_runtime.lens.sources import read_feed_source
from agent_runtime.lens.sources.transport import ReadReason

SECRET = "zq7Wx-9cJq-Kp4Rv"
HOME = "https://status.example.invalid/health"
ELSEWHERE = "https://collector.example.invalid/health"
HOME_HOST = "https://status.example.invalid:443"


def _feed(url: str = HOME, **extra) -> dict:
    return {"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
            "source": {"url": url, "selector": "$.cpu"}, "credential_ref": "k", **extra}


def _manifest(monitor_id: str, *feeds: dict) -> dict:
    return {"version": 1, "monitor_id": monitor_id, "feeds": list(feeds) or [_feed()], "rules": [],
            "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}, "persona_id": None}


def _call(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


@pytest.fixture
def wire(monkeypatch):
    """Every request the serve's own HTTP client would send: ``[(host, Authorization | None)]``."""

    from agent_runtime.lens.sources import transport

    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("authorization")))
        return httpx.Response(200, json={"cpu": 42})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(transport, "system_resolver", lambda host: ["93.184.216.34"])
    return seen


def _sign_in() -> dict:
    """A monitor that names ``k``, then the operator's sign-in for it — the sheet's order."""

    assert "result" in _call("runtime.lens.create", {"manifest": _manifest("status")})
    return _call("runtime.lens.credential.set", {"ref": "k", "scheme": "bearer", "secret": SECRET})


def test_a_preview_naming_a_held_ref_at_another_host_is_a_typed_gap_and_sends_no_authorization(wire):
    assert _sign_in()["result"]["set"] is True
    [own] = _call("runtime.lens.preview", {"manifest": _manifest("status")})["result"]["feeds"]
    assert (own["reason"], wire) == ("ok", [("status.example.invalid", f"Bearer {SECRET}")])

    del wire[:]
    [other] = _call("runtime.lens.preview", {"manifest": _manifest("proposed", _feed(ELSEWHERE))})["result"]["feeds"]
    assert wire == []  # not even an unauthenticated read: the gap is decided before a byte is sent
    assert other == {"feed_id": "api", "status": "unavailable", "number": None,
                     "reason": "credential_host_mismatch", "http_status": None}


@pytest.mark.parametrize("url", [
    "http://status.example.invalid/health",        # the same name in clear text
    "https://status.example.invalid:8443/health",  # another service on the same name
    "https://STATUS.example.invalid.evil.invalid/health",
])
def test_the_saved_address_is_scheme_name_and_port(wire, url):
    _sign_in()
    result = read_feed_source(_feed(url), resolver=lambda host: ["93.184.216.34"])
    assert (result.reason, wire) == (ReadReason.CREDENTIAL_HOST_MISMATCH, [])


def test_the_address_is_read_off_the_monitors_that_name_the_ref_never_off_the_request():
    reply = _sign_in()
    assert reply["result"] == {"ref": "k", "set": True, "rotated_at": reply["result"]["rotated_at"],
                               "host": HOME_HOST}
    assert _call("runtime.lens.credential.set", {"ref": "k", "scheme": "bearer", "secret": SECRET,
                                                "host": ELSEWHERE})["error"]["data"]["reason"] == "unknown_key"
    assert _call("runtime.lens.credential.set", {"ref": "nobody-names-me", "scheme": "bearer",
                                                "secret": SECRET})["error"]["data"]["reason"] == "credential_host_unknown"
    # A second monitor's draft names the ref at another address: a rotation can no longer say
    # which address the secret is for, and refuses rather than pick one.
    assert "result" in _call("runtime.lens.create", {"manifest": _manifest("proposed", _feed(ELSEWHERE))})
    rotated = _call("runtime.lens.credential.set", {"ref": "k", "scheme": "bearer", "secret": "another-value"})
    assert rotated["error"]["data"]["reason"] == "credential_host_ambiguous"
    assert resolve_credential("k", host=HOME_HOST).secret == SECRET  # the refused write changed nothing
    # ... and the monitor it was saved for reads it as before; the other one never does.
    [row] = _call("runtime.lens.get", {"monitor_id": "proposed"})["result"]["credentials"]
    assert (row["set"], row["host"]) == (False, HOME_HOST)
    [row] = _call("runtime.lens.get", {"monitor_id": "status"})["result"]["credentials"]
    assert (row["set"], row["host"]) == (True, HOME_HOST)


def test_a_credential_saved_before_hosts_were_recorded_is_never_sent(wire):
    """Fail closed: a row with no ``host`` (an older build's) reads as not signed in for every
    address until the person saves it again."""

    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "credentials": {
        "k": {"scheme": "bearer", "secret": SECRET, "rotated_at": "2026-10-16T12:00:00.000Z"}}}), encoding="utf-8")
    assert resolve_credential("k", host=HOME_HOST) is CredentialRefusal.HOST_MISMATCH
    assert credential_status("k", host=HOME_HOST) == {"ref": "k", "set": False, "host": None,
                                                      "rotated_at": "2026-10-16T12:00:00.000Z"}
    result = read_feed_source(_feed(), resolver=lambda host: ["93.184.216.34"])
    assert (result.reason, wire) == (ReadReason.CREDENTIAL_HOST_MISMATCH, [])


def test_an_inbound_route_secret_is_never_an_outbound_sign_in(wire):
    """An ingress route's secret is saved for no address (``host=None``): the door reads it,
    and a feed that names its ref sends nothing."""

    set_credential("ingress:r1", scheme="bearer", secret=SECRET, host=None)
    assert resolve_credential("ingress:r1", host=None).secret == SECRET
    result = read_feed_source(_feed(credential_ref="ingress:r1"), resolver=lambda host: ["93.184.216.34"])
    assert (result.reason, wire) == (ReadReason.CREDENTIAL_HOST_MISMATCH, [])
    set_credential("k", scheme="bearer", secret=SECRET, host=HOME_HOST)
    assert resolve_credential("k", host=None) is CredentialRefusal.HOST_MISMATCH  # nor the reverse


def test_a_prometheus_sign_in_is_for_the_base_address_its_reader_queries(wire):
    feed = {"version": 1, "id": "api", "kind": "prometheus", "interval_ms": 5000, "credential_ref": "k",
            "source": {"base_url": "https://prom.example.invalid/select/0", "query": "up"}}
    set_credential("k", scheme="bearer", secret=SECRET, host=credential_host("https://prom.example.invalid/"))
    read_feed_source(feed, resolver=lambda host: ["93.184.216.34"])
    assert wire == [("prom.example.invalid", f"Bearer {SECRET}")]
    del wire[:]
    feed["source"]["base_url"] = "https://prom.elsewhere.invalid/select/0"
    assert read_feed_source(feed, resolver=lambda host: ["93.184.216.34"]).reason is ReadReason.CREDENTIAL_HOST_MISMATCH
    assert wire == []
