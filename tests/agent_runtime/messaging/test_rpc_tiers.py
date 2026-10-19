"""p10-messaging M1: ``runtime.messaging.*`` — one ops table, ``status`` read, every write console, the
token verbs local-console only; the settings are declared and default off."""

from __future__ import annotations

from pathlib import Path


from agent_runtime import harness_settings, serve_rpc
from agent_runtime.call_authorization import (CALLER_DEVICE, LOCAL_CONSOLE, LOCAL_CONSOLE_METHODS, STDIO_OWNER,
                                              TIER_CONSOLE, TIER_READ, TRANSPORT_GATEWAY, RpcCaller, authorize_call)
from agent_runtime.messaging import rpc
from agent_runtime.serve_rpc import handle_request
from agent_runtime.serve_rpc.protocol import RpcContext

ROOT = Path(__file__).resolve().parents[3]
CONSOLE_DEVICE = RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id="dev_1", device_tier=TIER_CONSOLE)


def _call(method, params=None, caller=STDIO_OWNER):
    request = {"jsonrpc": "2.0", "id": method, "method": method, "params": params or {}}
    return handle_request(request, RpcContext(caller=caller))


def test_the_manifest_carries_the_ops_table_and_its_tiers():
    tiers = {name: tier for name, tier in serve_rpc.manifest()["tiers"].items() if name.startswith(rpc.METHOD_PREFIX)}
    assert tiers == rpc.TIERS
    assert [name for name, tier in tiers.items() if tier == TIER_READ] == ["runtime.messaging.status"]


def test_credential_verbs_are_local_console_only():
    """Killing mutation: ``runtime.messaging.credential.set`` leaves ``LOCAL_CONSOLE_METHODS`` → red."""
    token_verbs = {"runtime.messaging.credential.set", "runtime.messaging.credential.clear"}
    assert token_verbs <= LOCAL_CONSOLE_METHODS
    assert {n for n in LOCAL_CONSOLE_METHODS if n.startswith(rpc.METHOD_PREFIX)} == token_verbs
    for name in sorted(token_verbs):
        assert authorize_call(TIER_CONSOLE, CONSOLE_DEVICE, method=name).ok is False
        assert authorize_call(TIER_CONSOLE, LOCAL_CONSOLE, method=name).ok is True
    # Positive control: the same console device may bind a chat and allow an operator.
    assert authorize_call(TIER_CONSOLE, CONSOLE_DEVICE, method="runtime.messaging.binding.set").ok is True


def test_binding_set_refuses_an_unknown_instance_and_writes_a_known_one(monkeypatch):
    params = {"platform": "telegram", "chat_id": -1001, "persona_instance_id": "inst-ghost"}
    reply = _call("runtime.messaging.binding.set", params)
    assert reply["error"]["code"] == 4001 and reply["error"]["data"]["reason"] == "unknown_instance"
    monkeypatch.setattr(rpc, "_instance_known", lambda instance_id: instance_id == "inst-alice")
    reply = _call("runtime.messaging.binding.set", params | {"persona_instance_id": "inst-alice"})
    assert reply["result"]["binding"]["chat_id"] == "-1001"
    assert reply["result"]["binding"]["bound_by"] == "rpc:stdio_owner"
    listed = _call("runtime.messaging.binding.list", {"platform": "telegram"})["result"]["bindings"]
    assert [b["persona_instance_id"] for b in listed] == ["inst-alice"]
    assert _call("runtime.messaging.binding.clear", {"platform": "telegram", "chat_id": "-1001"})["result"] == {"cleared": True}


def test_operator_verbs_and_typed_refusals():
    assert _call("runtime.messaging.operator.allow", {"platform": "telegram", "user_id": 42, "display": "Max"})["result"]
    assert [o["user_id"] for o in _call("runtime.messaging.operator.list")["result"]["operators"]] == ["42"]
    assert _call("runtime.messaging.operator.revoke", {"platform": "telegram", "user_id": "42"})["result"] == {"revoked": True}
    reply = _call("runtime.messaging.operator.allow", {"platform": "carrier-pigeon", "user_id": "1"})
    assert reply["error"]["code"] == -32602 and reply["error"]["data"]["reason"] == "unknown_platform"
    reply = _call("runtime.messaging.operator.allow", {"platform": "telegram"})
    assert reply["error"]["data"] == {"reason": "invalid_request", "detail": "user_id"}


def test_status_reports_off_by_default(monkeypatch):
    import hermes_cli.config as config_module

    monkeypatch.setattr(config_module, "load_config_readonly", dict)
    result = _call("runtime.messaging.status")["result"]
    assert result == {"enabled": False, "default_persona": None,
                      "platforms": {"telegram": {"credential": "absent", "bindings": 0, "operators": 0,
                                                 "lane": {"state": "off", "reason": "not_serving"}}}}


def test_the_settings_are_declared_off_and_no_bundle_turns_them_on():
    """Every bundle switches the package off AND, applied to an empty config, leaves the setting off."""
    from agent_runtime.bundle_profiles.manifest import apply_to_config, load_profile
    from hermes_cli.plugins_manifest import parse_manifest_file

    plugin_dir = ROOT / "plugins" / "eternia-harness"
    schema = parse_manifest_file(plugin_dir / "plugin.yaml", plugin_dir, "bundled", "").config_schema
    assert schema["messaging_enabled"]["default"] is False and "messaging_default_persona" in schema
    for profile in ("bundled-desktop", "bundled-phone"):
        manifest = load_profile(profile, validate=False)
        assert "agent_runtime.messaging" in manifest.switched_off_modules, profile
        applied = apply_to_config(manifest, {})
        assert harness_settings.harness_setting("messaging_enabled", False, config=applied) is False, profile
