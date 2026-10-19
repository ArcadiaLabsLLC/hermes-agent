"""p10-messaging M1 §2.4: the bot token lives in the head profile behind the host-store seam, and it never
leaves through a reply, a receipt or a log."""

from __future__ import annotations

import json
import logging

import pytest

from agent_runtime.host_store import binding as host_binding
from agent_runtime.host_store.fake import FakeHostSecureStore
from agent_runtime.messaging import credentials, rpc
from agent_runtime.messaging.models import MessagingRefused, Platform, Reason
from agent_runtime.profile_home import get_hermes_head_home
from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.serve_rpc import handle_request
from agent_runtime.serve_rpc.protocol import RpcContext

TG = Platform.TELEGRAM
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"


@pytest.fixture(autouse=True)
def _unbound():
    host_binding.unbind_host_store()
    yield
    host_binding.unbind_host_store()


def _call(method, params=None):
    request = {"jsonrpc": "2.0", "id": method, "method": method, "params": params or {}}
    return handle_request(request, RpcContext(caller=STDIO_OWNER))


def test_unbound_the_token_is_one_file_in_the_head_home():
    assert credentials.bot_token(TG) is None and credentials.credential_state(TG) == "absent"
    credentials.set_token(TG, f"  {TOKEN} ")
    path = get_hermes_head_home() / "messaging" / "credentials.json"
    assert json.loads(path.read_text(encoding="utf-8"))["telegram"]["bot_token"] == TOKEN
    assert credentials.bot_token(TG) == TOKEN and credentials.credential_state(TG) == "present"
    assert credentials.clear_token(TG) is True and not path.exists()
    assert credentials.clear_token(TG) is False and credentials.bot_token(TG) is None


def test_bound_store_leaves_no_plaintext():
    """Killing mutation: ``credentials._store_token_file`` drops its ``secret_files.bound()`` arm (always the disk) → red."""
    head = get_hermes_head_home()
    path = credentials.credentials_path(head)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"telegram": {"bot_token": "999:stale-plaintext-left-behind-xxxxx"}}), encoding="utf-8")
    store = FakeHostSecureStore()
    store.bind(profile="base", store_root=head)

    credentials.set_token(TG, TOKEN)
    assert not path.exists()
    (slot,) = store.slots
    assert slot.endswith("messaging/credentials.json") and TOKEN in store.slots[slot].decode("utf-8")
    assert credentials.bot_token(TG) == TOKEN
    assert credentials.clear_token(TG) is True and store.slots == {} and not path.exists()


def test_the_env_override_is_read_from_the_head_profile_scope_and_wins(monkeypatch):
    credentials.set_token(TG, TOKEN)
    other = "555555:OverrideTokenFromTheSecretManager_xyz"
    monkeypatch.setenv(credentials.env_key(TG), "777:process-env-is-not-the-profile-scope-xx")
    assert credentials.bot_token(TG) == TOKEN  # os.environ alone is not the profile's scope
    (get_hermes_head_home() / ".env").write_text(f"{credentials.env_key(TG)}={other}\n", encoding="utf-8")
    assert credentials.bot_token(TG) == other


def test_a_malformed_token_is_refused_without_echoing_it():
    with pytest.raises(MessagingRefused) as refused:
        credentials.set_token(TG, "not-a-telegram-token-SECRETVALUE")
    assert refused.value.reason is Reason.TOKEN_INVALID and "SECRETVALUE" not in str(refused.value)
    reply = _call("runtime.messaging.credential.set", {"platform": "telegram", "token": "bad SECRETVALUE"})
    assert reply["error"]["data"]["reason"] == "token_invalid" and "SECRETVALUE" not in json.dumps(reply)


def test_token_never_on_the_wire(caplog):
    """Killing mutation: ``rpc._credential_set`` answers (or ``status`` reports, or a receipt carries) the
    token itself → red. Every reply, every receipt and every log line of the token's whole life is read."""
    caplog.set_level(logging.DEBUG)
    replies = [
        _call("runtime.messaging.credential.set", {"platform": "telegram", "token": TOKEN}),
        _call("runtime.messaging.status"),
        _call("runtime.messaging.credential.clear", {"platform": "telegram"}),
    ]
    assert replies[0]["result"] == {"platform": "telegram", "credential": "present"}
    assert replies[1]["result"]["platforms"]["telegram"]["credential"] == "present"
    assert replies[2]["result"]["cleared"] is True and replies[2]["result"]["credential"] == "absent"
    receipts = [r.getMessage() for r in caplog.records if r.name == "agent_runtime.work_store.receipts"]
    assert any('"messaging.credential.set"' in line for line in receipts)  # the receipt did land
    secret = TOKEN.split(":", 1)[1]
    assert secret not in json.dumps(replies)
    assert not [r for r in caplog.records if secret in r.getMessage()]


def test_a_crash_answers_a_fixed_sentence(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError(f"disk said {TOKEN}")
    monkeypatch.setattr(credentials, "set_token", boom)
    reply = rpc._rpc_reply("r", "credential.set", {"platform": "telegram", "token": TOKEN}, "rpc:test")
    assert reply["error"]["data"] == {"reason": "messaging_unavailable"} and TOKEN not in json.dumps(reply)
