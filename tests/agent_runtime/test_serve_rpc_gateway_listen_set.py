"""``runtime.gateway.listen.set`` — the LAN gateway's listen pair, one narrow typed write.

Row ``RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES``, family "gateway": Eternia's two
``hermes config set`` children become ONE method that writes the two harness keys and nothing else (never a
generic config write over RPC — review w1118a.69). Witness: the raw config file. Killing mutations per test.
"""

from __future__ import annotations

import pytest

from agent_runtime import serve_rpc

SETTINGS = ("plugins", "entries", "eternia-harness", "settings")


def _rpc(**params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "g", "method": "runtime.gateway.listen.set",
                                     "params": params})


def _settings() -> dict:
    from hermes_cli.config import read_user_config_raw

    node = read_user_config_raw()
    for segment in SETTINGS:
        node = (node or {}).get(segment) or {}
    return node


def _raw() -> dict:
    from hermes_cli.config import read_user_config_raw

    return read_user_config_raw()


def test_enable_writes_the_host_and_port_and_keeps_every_other_key():
    """Mutation: drop the ``port`` write -> the stored port stays unset, red."""
    from hermes_cli.config import read_user_config_raw, save_config

    seeded = read_user_config_raw()
    seeded["display"] = {"language": "ja"}
    save_config(seeded)

    reply = _rpc(listen="0.0.0.0", port=8765)
    assert reply["result"] == {"listen": "0.0.0.0", "port": 8765, "changed": True}
    assert _settings() == {"remote_gateway_listen": "0.0.0.0", "remote_gateway_port": 8765}
    assert _raw()["display"] == {"language": "ja"}

    again = _rpc(listen="0.0.0.0", port=8765)["result"]
    assert again["changed"] is False


def test_off_is_written_as_false_and_stays():
    """Mutation: answer ``None`` for off in ``_listen_value`` -> the key holds null, not ``false``, red."""
    _rpc(listen="0.0.0.0", port=9001)
    reply = _rpc(listen=False)
    assert reply["result"] == {"listen": False, "port": 9001, "changed": True}
    assert _settings()["remote_gateway_listen"] is False


@pytest.mark.parametrize("params,field", [
    ({"listen": "lan.example"}, "listen"), ({"listen": True}, "listen"), ({"listen": ""}, "listen"),
    ({"listen": "0.0.0.0", "port": 0}, "port"), ({"listen": "0.0.0.0", "port": 70000}, "port"),
    ({"listen": "0.0.0.0", "port": "8765"}, "port"), ({"listen": "0.0.0.0", "port": True}, "port"),
])
def test_a_bad_value_is_refused_and_writes_nothing(params, field):
    """Mutation: accept any string in ``_listen_value`` -> the hostname case writes, red."""
    before = _raw()
    reply = _rpc(**params)
    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"] == {"reason": "invalid_request", "field": field}
    assert _raw() == before


@pytest.mark.parametrize("params", [{}, {"port": 8765}, {"listen": "0.0.0.0", "key": "model.default"},
                                    {"listen": "0.0.0.0", "value": "x"}])
def test_it_is_never_a_general_config_write(params):
    """Mutation: let extra params through -> a caller names another key, red."""
    before = _raw()
    reply = _rpc(**params)
    assert reply["error"]["data"] == {"reason": "invalid_request"}
    assert _raw() == before


def test_a_managed_install_is_refused(monkeypatch):
    import hermes_cli.config as config

    monkeypatch.setattr(config, "is_managed", lambda: True)
    reply = _rpc(listen="0.0.0.0")
    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"] == {"reason": "config_managed"}


def test_only_this_installs_console_may_call_it():
    """Mutation: drop it from ``LOCAL_CONSOLE_METHODS`` -> a paired console device could move the listener, red."""
    from agent_runtime.call_authorization import LOCAL_CONSOLE_METHODS
    from agent_runtime.serve_rpc.registry import manifest

    assert "runtime.gateway.listen.set" in LOCAL_CONSOLE_METHODS
    assert "runtime.gateway.listen.set" in manifest()["methods"]
