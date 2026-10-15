"""``runtime.realm.*`` — the ten realm argv twins, one implementation each.

Argv census rows 1-10. Each method and its argv verb call the same function in
``agent_runtime.realm_verbs``; the method's result is the argv ``--json``
envelope.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent_runtime import realm_verbs, serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE_METHODS, TIER_CONSOLE
from agent_runtime.realm_membership import RealmSyncCredential
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND
from agent_runtime.serve_rpc.realm import REALM_METHODS
from agent_runtime.store import RealmStore
from hermes_cli.harness_parts import realm_commands

SECRET = "tok-must-never-echo"


def _rpc(method: str, params, rid: str = "rv"):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})


def _credential(realm_id: str = "realm_x") -> dict:
    return {
        "schema_version": 1, "realm_id": realm_id, "api_base": "https://api.invalid", "api_token": SECRET,
        "git_url": "https://git.invalid/r.git", "git_authorization": "Bearer " + SECRET,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }


def _argv_envelope(handler, capsys, **fields) -> tuple[int, dict]:
    code = handler(SimpleNamespace(json=True, output=None, fields=None, quiet=False, **fields))
    return code, json.loads(capsys.readouterr().out)


def test_the_ten_are_registered_console_and_remote_answerable():
    manifest = serve_rpc.manifest()
    assert len(REALM_METHODS) == 10
    for name in REALM_METHODS:
        assert name in manifest["methods"]
        assert manifest["tiers"][name] == TIER_CONSOLE
        assert name not in LOCAL_CONSOLE_METHODS


#: method, realm_verbs function, method params, argv handler, argv fields,
#: and the call both doors must make.
_CASES = [
    ("runtime.realm.sync.pull", "realm_sync_pull", {"realm_id": "r", "dry_run": True},
     "_cmd_realm_sync_pull", {"realm_id": "r", "dry_run": True, "credential_file": None},
     (("r",), {"credential": None, "dry_run": True})),
    ("runtime.realm.sync.publish", "realm_sync_publish", {"realm_id": "r", "yes": True},
     "_cmd_realm_sync_publish", {"realm_id": "r", "yes": True, "dry_run": False, "credential_file": None},
     (("r",), {"credential": None, "dry_run": False})),
    ("runtime.realm.sync.revert", "realm_sync_revert",
     {"realm_id": "r", "items": ["office_actor:ws:a"], "to": "abc", "yes": True},
     "_cmd_realm_sync_revert",
     {"realm_id": "r", "items": ["office_actor:ws:a"], "revert_all": False, "to": "abc", "yes": True, "dry_run": False},
     (("r",), {"items": ["office_actor:ws:a"], "revert_all": False, "to": "abc", "dry_run": False})),
    ("runtime.realm.sync.resolve", "realm_sync_resolve",
     {"realm_id": "r", "key": "skill::s", "take": "local", "dry_run": True},
     "_cmd_realm_sync_resolve", {"realm_id": "r", "key": "skill::s", "take": "local", "dry_run": True, "yes": False},
     (("r",), {"key": "skill::s", "take": "local", "dry_run": True})),
    ("runtime.realm.skills.show", "realm_skills_show", {"realm_id": "r"},
     "_cmd_realm_skills_show", {"realm_id": "r"}, (("r",), {})),
    ("runtime.realm.skills.set", "realm_skills_set", {"realm_id": "r", "skills": ["a", "b"]},
     "_cmd_realm_skills_set",
     {"realm_id": "r", "publish_all": False, "skills": "a,b", "publish_none": False, "dry_run": False},
     (("r",), {"publish_all": False, "skills": ["a", "b"], "publish_none": False, "dry_run": False})),
    ("runtime.realm.agents.show", "realm_agents_show", {"realm_id": "r"},
     "_cmd_realm_agents_show", {"realm_id": "r"}, (("r",), {})),
    ("runtime.realm.agents.set", "realm_agents_set", {"realm_id": "r", "workspace": True, "dry_run": True},
     "_cmd_realm_agents_set",
     {"realm_id": "r", "publish_workspace": True, "agents": None, "publish_none": False, "dry_run": True},
     (("r",), {"publish_workspace": True, "agents": None, "publish_none": False, "dry_run": True})),
]


@pytest.mark.parametrize("case", _CASES, ids=[case[0] for case in _CASES])
def test_the_method_and_the_argv_verb_reach_one_implementation(case, monkeypatch, capsys):
    name, function, params, handler, fields, expected_call = case
    calls: list[tuple] = []
    envelope = {"schema_version": 1, "kind": "probe", "id": "r"}

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(envelope)

    monkeypatch.setattr(realm_verbs, function, spy)
    assert _rpc(name, params)["result"] == envelope
    code, printed = _argv_envelope(getattr(realm_commands, handler), capsys, **fields)
    assert (code, printed) == (0, envelope)
    assert calls == [expected_call, expected_call]


def test_status_and_adopt_parse_the_inline_credential_and_never_echo_it(monkeypatch):
    seen: list = []

    def status(realm_id, *, credential=None):
        seen.append(credential)
        return {"realm_id": realm_id}

    monkeypatch.setattr(realm_verbs, "realm_sync_status", status)
    assert _rpc("runtime.realm.sync.status", {"realm_id": "realm_x", "credential": _credential()})["result"]
    assert isinstance(seen[0], RealmSyncCredential) and seen[0].realm_id == "realm_x"
    bad = _rpc("runtime.realm.sync.status", {"realm_id": "realm_x", "credential": {**_credential(), "api_token": ""}})
    assert bad["error"]["code"] == ERR_CONFLICT and bad["error"]["data"]["reason"] == "sync_auth_failed"
    adopt = _rpc("runtime.realm.adopt", {})["error"]
    assert adopt["data"]["reason"] == "sync_auth_failed"
    assert SECRET not in json.dumps([bad, adopt])


def test_destructive_verbs_refuse_without_yes_and_run_nothing(monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("ran without confirmation")

    for function in ("realm_sync_publish", "realm_sync_revert", "realm_sync_resolve"):
        monkeypatch.setattr(realm_verbs, function, never)
    for name, params in (("runtime.realm.sync.publish", {"realm_id": "r"}),
                         ("runtime.realm.sync.revert", {"realm_id": "r", "all": True}),
                         ("runtime.realm.sync.resolve", {"realm_id": "r", "key": "k", "take": "remote"})):
        error = _rpc(name, params)["error"]
        assert error["code"] == ERR_INVALID_PARAMS and error["data"]["reason"] == "confirmation_required", name


def test_selection_is_written_and_read_back_through_the_store():
    realm = RealmStore().create(name="Selection realm")
    result = _rpc("runtime.realm.skills.set", {"realm_id": realm.id, "skills": ["alpha", "beta"]})["result"]
    assert (result["kind"], result["mode"], result["selection"]) == ("realm_skill_selection", "selected",
                                                                     ["alpha", "beta"])
    assert sorted(RealmStore().get(realm.id).skill_selection) == ["alpha", "beta"]
    assert _rpc("runtime.realm.skills.show", {"realm_id": realm.id})["result"] == result
    both = _rpc("runtime.realm.skills.set", {"realm_id": realm.id, "all": True, "none": True})["error"]
    assert both["code"] == ERR_INVALID_PARAMS and both["data"]["reason"] == "invalid_request"
    assert "--all" in both["message"]


def test_typed_refusals_for_params_and_unknown_realms():
    missing = _rpc("runtime.realm.sync.status", {})["error"]
    assert missing["code"] == ERR_INVALID_PARAMS and missing["data"]["reason"] == "invalid_request"
    take = _rpc("runtime.realm.sync.resolve", {"realm_id": "r", "key": "k", "take": "both", "yes": True})["error"]
    assert take["data"]["reason"] == "invalid_request"
    unknown = _rpc("runtime.realm.skills.show", {"realm_id": "realm_does_not_exist"})["error"]
    assert unknown["code"] == ERR_NOT_FOUND and unknown["data"]["reason"] == "not_found"
    # The store's NotFound text is the realm file's absolute path; it stays home.
    assert unknown["message"] == "Realm not found." and "realm_does_not_exist" not in json.dumps(unknown)
