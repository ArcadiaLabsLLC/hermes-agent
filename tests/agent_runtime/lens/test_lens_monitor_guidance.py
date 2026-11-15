"""A monitor's plain-language rules and the workspace default (row ``RT-LENS-MONITOR-RULES``,
``agent_runtime/lens/guidance.py``, design ``planned/lens-act-and-safe-investigate.md`` §2).

Gates and their killing mutations (each red recorded in the row's commit):

* a monitor with no rules anywhere runs under the shipped text, and one with no rules of its own
  under its workspace's default once that is set, while another workspace's monitor keeps the
  shipped text — killed by keying ``guidance_defaults`` on ``""`` for every workspace (``_key``);
* a monitor's own rules win, and a waiting draft's changed rules show as ``draft`` while the sealed
  text still runs, until the reseal — killed by ``monitor_guidance`` reading the draft first;
* a manifest without rules seals to the same bytes as before the key existed — killed by
  emitting ``guidance: null`` for an absent key;
* blank rules are refused — killed by dropping the ``strip`` check from ``read_guidance``;
* ``default.set`` with ``text: null`` forgets the workspace's text — killed by skipping the DELETE.
"""

from __future__ import annotations

import pytest

from agent_runtime.lens.guidance import SHIPPED_GUIDANCE
from agent_runtime.lens.store import LensStore, MonitorState


def _call(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _rpc(method: str, params: dict) -> dict:
    reply = _call(method, params)
    assert "error" not in reply, reply
    return reply["result"]


def _manifest(monitor_id: str, guidance: str | None = None) -> dict:
    feed = {"version": 1, "id": "latency", "kind": "http_json", "interval_ms": 60_000,
            "source": {"url": "https://status.example.invalid/api", "selector": "$.latency"}}
    manifest = {"version": 1, "monitor_id": monitor_id, "feeds": [feed], "rules": [],
                "automation": {"level": "notify", "when": "always", "daily_turn_cap": 4}, "persona_id": None}
    if guidance is not None:
        manifest["guidance"] = guidance
    return manifest


def _monitor(monitor_id: str, workspace_id: str, guidance: str | None = None) -> dict:
    _rpc("runtime.lens.create", {"manifest": _manifest(monitor_id, guidance), "workspace_id": workspace_id})
    LensStore().seal(monitor_id)
    LensStore().set_state(monitor_id, MonitorState.ENABLED)
    return _rpc("runtime.lens.get", {"monitor_id": monitor_id})


def _guidance(monitor_id: str) -> dict:
    return _rpc("runtime.lens.get", {"monitor_id": monitor_id})["guidance"]


def test_a_monitor_without_rules_follows_its_workspace_default_and_else_the_shipped_text():
    _monitor("alpha", "ws_a")
    _monitor("beta", "ws_b")
    assert _guidance("alpha") == {"text": SHIPPED_GUIDANCE, "source": "shipped", "draft": None}
    assert _rpc("runtime.lens.guidance.default.get", {"workspace_id": "ws_a"})["source"] == "shipped"

    written = _rpc("runtime.lens.guidance.default.set",
                   {"workspace_id": "ws_a", "text": "Only look when latency doubles.\nNever post."})
    assert written["source"] == "workspace" and written["shipped_text"] == SHIPPED_GUIDANCE
    assert _guidance("alpha") == {"text": "Only look when latency doubles.\nNever post.", "source": "workspace",
                                  "draft": None}
    assert _guidance("beta") == {"text": SHIPPED_GUIDANCE, "source": "shipped", "draft": None}


def test_a_monitors_own_rules_win_and_a_changed_draft_shows_until_the_reseal():
    _rpc("runtime.lens.guidance.default.set", {"workspace_id": "ws_a", "text": "Workspace rules."})
    first = _monitor("alpha", "ws_a", guidance="Investigate a 50% jump only.")
    assert _guidance("alpha") == {"text": "Investigate a 50% jump only.", "source": "monitor", "draft": None}

    _rpc("runtime.lens.create", {"manifest": _manifest("alpha", "Investigate any jump."), "workspace_id": "ws_a"})
    assert _guidance("alpha") == {"text": "Investigate a 50% jump only.", "source": "monitor",
                                  "draft": {"text": "Investigate any jump.", "source": "monitor"}}

    resealed = _rpc("runtime.lens.seal", {"monitor_id": "alpha"})
    assert resealed["sealed"]["revision"] == first["sealed"]["revision"] + 1
    assert resealed["sealed"]["digest"] != first["sealed"]["digest"]
    assert _guidance("alpha") == {"text": "Investigate any jump.", "source": "monitor", "draft": None}


def test_a_manifest_without_rules_seals_to_its_old_bytes():
    sealed = _monitor("alpha", "ws_a")["sealed"]
    assert "guidance" not in sealed["manifest"]
    with LensStore().connection() as conn:
        body = conn.execute("SELECT body FROM monitors WHERE monitor_id = 'alpha'").fetchone()[0]
    assert b"guidance" not in bytes(body)


@pytest.mark.parametrize("text", ["", "   \n\t", "x" * 4097])
def test_blank_or_oversized_rules_are_refused(text):
    reply = _call("runtime.lens.create", {"manifest": _manifest("alpha", text), "workspace_id": "ws_a"})
    assert reply["error"]["data"]["reason"] in {"invalid_value", "invalid_string"}, reply
    reply = _call("runtime.lens.guidance.default.set", {"workspace_id": "ws_a", "text": text})
    assert reply["error"]["data"]["reason"] in {"invalid_value", "invalid_string"}, reply


def test_setting_the_default_to_null_restores_the_shipped_text():
    _monitor("alpha", "ws_a")
    _rpc("runtime.lens.guidance.default.set", {"workspace_id": "ws_a", "text": "Workspace rules."})
    cleared = _rpc("runtime.lens.guidance.default.set", {"workspace_id": "ws_a", "text": None})
    assert cleared == {"workspace_id": "ws_a", "text": SHIPPED_GUIDANCE, "source": "shipped",
                       "updated_at_ms": None, "shipped_text": SHIPPED_GUIDANCE}
    assert _guidance("alpha")["source"] == "shipped"
    reply = _call("runtime.lens.guidance.default.set", {"workspace_id": "ws_a"})
    assert reply["error"]["data"] == {"reason": "missing_key", "detail": "text"}
