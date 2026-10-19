"""Backend ``realm.revoked`` -> the durable local mark (``realm_sync.revocation``).

The launcher records the event through ``runtime.realm.revoked``; the realm
and its local data stay, the snapshot's ``sync`` object carries ``revoked``,
and every credentialed sync verb refuses ``realm_revoked`` (not retryable)
before any network call. A re-adopt (re-grant) lifts the mark.
"""

from __future__ import annotations

import pytest

from agent_runtime import serve_rpc
from agent_runtime.realm_sync import RealmSyncError
from agent_runtime.realm_sync.git import _authorize
from agent_runtime.realm_sync.revocation import (
    RealmRevokedReason,
    mark_realm_revoked,
    read_realm_revocation,
    realm_revocation_path,
)
from agent_runtime.realm_sync.sidecar import read_realm_sync_sidecar
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS
from agent_runtime.store import RealmStore


@pytest.fixture
def realm(isolate_agent_runtime_root):
    return RealmStore().create(name="Revoked", server_id="srv_9", realm_id="realm_rv")


def _rpc(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "rv", "method": method, "params": params})


def test_the_method_records_the_mark_and_keeps_the_realm(realm):
    reply = _rpc("runtime.realm.revoked", {"realm_id": realm.id, "reason": "membership_kicked"})
    result = reply["result"]
    assert result["kind"] == "realm_revocation"
    assert (result["realm_id"], result["reason"], result["host_state"]) == (realm.id, "membership_kicked", False)
    assert realm_revocation_path(realm.id).is_file()
    assert RealmStore().get(realm.id).id == realm.id  # local data kept


def test_an_unknown_reason_is_invalid_request(realm):
    reply = _rpc("runtime.realm.revoked", {"realm_id": realm.id, "reason": "felt_like_it"})
    assert reply["error"]["code"] == ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "invalid_request"
    assert read_realm_revocation(realm.id) is None


def test_a_revoked_realm_refuses_every_sync_action_before_the_network(realm, monkeypatch):
    import agent_runtime.realm_membership as membership

    monkeypatch.setattr(membership, "_request_json", lambda *a, **k: pytest.fail("no backend call for a revoked realm"))
    mark_realm_revoked(realm, RealmRevokedReason.GIT_HOST_UNBOUND)
    for action in ("pull", "publish", "status"):
        with pytest.raises(RealmSyncError) as excinfo:
            _authorize(realm, action, None, None)
        assert excinfo.value.code == "realm_revoked"
        assert excinfo.value.retryable is False
        assert excinfo.value.safe_details == {"revoked_reason": "git_host_unbound", "host_state": True}


def test_a_revoked_sync_verb_answers_conflict_on_the_method_lane(realm):
    mark_realm_revoked(realm, RealmRevokedReason.ROLE_REVOKED)
    reply = _rpc("runtime.realm.sync.pull", {"realm_id": realm.id})
    assert reply["error"]["code"] == ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == "realm_revoked"
    assert reply["error"]["data"]["retryable"] is False
    assert reply["error"]["data"]["revoked_reason"] == "role_revoked"


def test_the_snapshot_sync_object_carries_the_mark_even_unchecked(realm):
    assert read_realm_sync_sidecar(realm.id) is None
    mark_realm_revoked(realm, RealmRevokedReason.SERVER_DELETED)
    sync = read_realm_sync_sidecar(realm.id)
    assert sync is not None
    assert sync["revoked"]["reason"] == "server_deleted"
    assert sync["state"] is None


def test_a_repeat_mark_keeps_the_first_timestamp(realm):
    first = mark_realm_revoked(realm, RealmRevokedReason.GRANT_REMOVED)
    again = mark_realm_revoked(realm, RealmRevokedReason.GRANT_REMOVED)
    assert again["revoked_at"] == first["revoked_at"]


def test_a_re_adopt_lifts_the_mark(realm, monkeypatch):
    import agent_runtime.realm_membership as membership
    from agent_runtime.realm_membership import RealmSyncCredential, adopt_realms

    mark_realm_revoked(realm, RealmRevokedReason.MEMBERSHIP_LEFT)
    items = [{"id": realm.id, "server_id": "srv_9", "name": "Revoked", "slug": "revoked", "git_url": ""}]
    monkeypatch.setattr(membership, "_request_json", lambda *a, **k: (200, {"items": items}))
    credential = RealmSyncCredential.parse({
        "schema_version": 1, "realm_id": realm.id, "api_base": "https://api.test.invalid/api",
        "api_token": "etk_t", "git_url": "https://git.test.invalid/r.git",
        "git_authorization": "Basic x", "expires_at": "2999-01-01T00:00:00Z",
    })
    adopt_realms(credential)
    assert read_realm_revocation(realm.id) is None
    _authorize(RealmStore().get(realm.id), "pull", membership.RealmMembershipProvider(), None)  # no raise


# --- RT-MAP-BACKEND-409-REALMS: the mint's permanent 409s are host-state marks ---


def _admitted_credential(realm_id: str):
    from agent_runtime.realm_membership import RealmSyncCredential

    return RealmSyncCredential.parse({
        "schema_version": 1, "realm_id": realm_id, "api_base": "https://api.test.invalid/api",
        "api_token": "etk_t", "git_url": "https://git.test.invalid/r.git",
        "git_authorization": "Basic x", "expires_at": "2999-01-01T00:00:00Z",
    })


@pytest.mark.parametrize(
    ("backend_code", "reason"),
    [("realms.git_host_binding_lost", "git_host_binding_lost"), ("realms.git_host_unbound", "git_host_unbound")],
)
def test_a_mint_409_is_a_permanent_host_state_refusal_not_unreachable(realm, backend_code, reason):
    reply = _rpc("runtime.realm.revoked", {"realm_id": realm.id, "reason": backend_code})
    assert (reply["result"]["reason"], reply["result"]["host_state"]) == (reason, True)
    with pytest.raises(RealmSyncError) as excinfo:
        _authorize(realm, "pull", None, None)
    assert excinfo.value.code == "realm_revoked"  # never sync_remote_unreachable
    assert excinfo.value.retryable is False
    assert excinfo.value.safe_details == {"revoked_reason": reason, "host_state": True}


def test_an_admitted_credential_lifts_a_host_state_mark(realm, monkeypatch):
    import agent_runtime.realm_membership as membership

    _rpc("runtime.realm.revoked", {"realm_id": realm.id, "reason": "realms.git_host_binding_lost"})
    monkeypatch.setattr(membership, "_request_json", lambda *a, **k: (200, {"allowed": True}))
    realm.sync_manifest_ref = "https://git.test.invalid/r.git"
    _authorize(realm, "pull", None, _admitted_credential(realm.id))  # a fresh mint re-verified the binding
    assert read_realm_revocation(realm.id) is None


def test_an_admitted_credential_never_lifts_a_membership_mark(realm):
    mark_realm_revoked(realm, RealmRevokedReason.MEMBERSHIP_BANNED)
    with pytest.raises(RealmSyncError) as excinfo:
        _authorize(realm, "pull", None, _admitted_credential(realm.id))
    assert excinfo.value.code == "realm_revoked"
    assert read_realm_revocation(realm.id) is not None


def test_an_ownership_transfer_parses_and_is_a_member_reason_not_host_state(realm):
    """RT-REALM-REVOKED-OWNERSHIP-TRANSFERRED: the backend's newest reason is accepted."""
    reply = _rpc("runtime.realm.revoked", {"realm_id": realm.id, "reason": "ownership_transferred"})
    result = reply["result"]
    assert (result["reason"], result["host_state"]) == ("ownership_transferred", False)
    assert RealmRevokedReason("ownership_transferred") is RealmRevokedReason.OWNERSHIP_TRANSFERRED
    assert read_realm_revocation(realm.id)["reason"] == "ownership_transferred"
