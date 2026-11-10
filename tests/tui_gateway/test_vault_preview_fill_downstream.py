"""Fork half of ``tests/tui_gateway/test_vault_preview_fill.py``'s compute-host relay cases.

Upstream's relay (v0.23.1, #150283) treats any ``supervisor.respond`` as delivered, so its stubs
return ``None`` or a bare bool. The fork's ``_answer_compute_host_request`` (7ac130330d) keeps the
mirrored request until the CHILD acknowledges it (``respond.ack`` with status ok/expired), so those
stubs read as "acknowledgement unavailable" here. These cases drive the same vault behaviour —
live-only resolution, redaction of an echoed UI-filled password in the owning profile before the
child, and an untouched non-preview reply — through a child that acknowledges.
"""

from __future__ import annotations

import json
import threading
import types

import pytest

import tui_gateway.server as srv

_ACK = {"type": "respond.ack", "response": {"result": {"status": "ok"}}}
_SECRET = "synthetic-isolated-fill-pw-150283"


def test_relayed_preview_vault_request_is_live_only_and_still_resolves(monkeypatch):
    from tui_gateway import server_requests

    sid = "preview-vault-live-only-fork"
    session = {"history_lock": threading.Lock()}
    monkeypatch.setitem(srv._sessions, sid, session)
    monkeypatch.setattr(server_requests, "_answerable", lambda _sid: True)
    monkeypatch.setattr(srv, "write_json", lambda _frame: True)
    monkeypatch.setattr(srv, "_session_uses_compute_host", lambda _session: True)

    def respond(_sid, params):
        assert server_requests.resolve_response(params["frame"])
        return _ACK

    monkeypatch.setattr(srv, "_get_compute_host_supervisor", lambda: types.SimpleNamespace(respond=respond))
    expression = '(() => "synthetic-secret-never-replayed")()'

    def deliver(frame):
        assert frame["params"]["vault"]["expression"] == expression
        assert server_requests._open[frame["id"]].params == {}
        assert srv._relay_compute_host_rpc(frame)
        assert expression not in json.dumps(session["_compute_host_open_request"])
        assert srv._open_requests(sid) == []
        assert srv._relay_compute_host_response({"id": frame["id"], "result": {"value": '{"success": true}'}})
        # The child acknowledged: the parent's mirror is gone.
        assert "_compute_host_open_request" not in session

    monkeypatch.setattr(server_requests, "_write", deliver)
    try:
        result = srv._ask("preview.act", sid, {
            "action": "vault", "vault": {"operation": "evaluate", "target": "bound-page", "expression": expression},
        }, timeout=0)
    finally:
        srv._sessions.pop(sid, None)
    assert json.loads(result) == {"success": True}
    assert srv._open_requests(sid) == []
    assert server_requests.open_request_count() == 0


def _forward(monkeypatch, method, echoed_value):
    """The value the acknowledging child was handed for one relayed reply."""
    sid = "preview-read-isolation-fork"
    session = {"history_lock": threading.Lock(), "profile_home": "",
               "_compute_host_open_request": {"id": "srq-abc", "method": method}}
    monkeypatch.setitem(srv._sessions, sid, session)
    monkeypatch.setattr(srv, "_session_uses_compute_host", lambda _session: True)
    captured = {}

    def respond(_sid, params):
        captured["frame"] = params["frame"]
        return _ACK

    monkeypatch.setattr(srv, "_get_compute_host_supervisor", lambda: types.SimpleNamespace(respond=respond))
    try:
        assert srv._relay_compute_host_response({"id": "srq-abc", "result": {"value": echoed_value}})
    finally:
        srv._sessions.pop(sid, None)
    return captured["frame"]["result"]["value"]


@pytest.mark.parametrize("method", ["preview.read", "preview.act"])
def test_relayed_preview_reply_is_redacted_in_the_owning_profile_before_the_child(monkeypatch, method):
    from agent.redact import clear_vault_redaction_values, register_vault_redaction_value

    register_vault_redaction_value(_SECRET)
    try:
        echoed = json.dumps({"success": True, "text": _SECRET, "elements": [{"label": _SECRET}],
                             "error": f"login failed for {_SECRET}"})
        forwarded = _forward(monkeypatch, method, echoed)
    finally:
        clear_vault_redaction_values()
    assert _SECRET not in forwarded and "redacted-vault-secret" in forwarded


def test_relayed_non_preview_reply_is_forwarded_untouched(monkeypatch):
    from agent.redact import clear_vault_redaction_values, register_vault_redaction_value

    register_vault_redaction_value(_SECRET)
    try:
        value = json.dumps({"ok": True, "note": _SECRET})
        forwarded = _forward(monkeypatch, "clarify", value)
    finally:
        clear_vault_redaction_values()
    assert forwarded == value
