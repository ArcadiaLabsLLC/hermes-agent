"""The credential's SUBJECT: the frozen JSON's ``realm_id`` carries a subject ref.

Backend 02 §5 / §4c and the education git-course lane Stage 5: ``course:<id>``
is a course clone credential. A credential minted for another subject never
authorizes a realm's sync, server-bound or server-less.
"""

from __future__ import annotations

import pytest

from hermes_time import now

from agent_runtime.models import Realm
from agent_runtime.realm_membership import CredentialSubject, RealmSyncCredential, select_membership_provider
from agent_runtime.realm_sync import RealmSyncError
from agent_runtime.realm_sync.git import _authorize


def _credential(realm_id: str) -> RealmSyncCredential:
    return RealmSyncCredential.parse({
        "schema_version": 1,
        "realm_id": realm_id,
        "api_base": "https://api.test.invalid/api",
        "api_token": "etk_subject_token",
        "git_url": "https://git.test.invalid/subject.git",
        "git_authorization": "Basic x-access-token:subject",
        "expires_at": "2999-01-01T00:00:00Z",
    })


def _realm(realm_id: str = "alpha", server_id: str | None = None, ref: str | None = None) -> Realm:
    ts = now()
    return Realm(id=realm_id, slug=realm_id, name=realm_id, created_at=ts, updated_at=ts,
                 server_id=server_id, sync_manifest_ref=ref)


def test_course_ref_parses_as_a_course_subject():
    credential = _credential("course:crs_42")
    assert credential.subject is CredentialSubject.COURSE
    assert credential.subject_id == "crs_42"
    assert credential.realm_id == "course:crs_42"  # the frozen key is never rewritten


def test_a_plain_id_is_a_server_realm_subject():
    credential = _credential("realm_1")
    assert credential.subject is CredentialSubject.SERVER_REALM
    assert credential.subject_id == "realm_1"


@pytest.mark.parametrize("server_id", [None, "srv_1"])
def test_a_course_credential_never_authorizes_a_realm(server_id):
    realm = _realm("crs_42", server_id=server_id, ref="https://git.test.invalid/r.git")
    with pytest.raises(RealmSyncError) as excinfo:
        select_membership_provider(realm, _credential("course:crs_42"))
    assert excinfo.value.code == "sync_auth_failed"
    assert excinfo.value.safe_details == {"credential_subject": "course"}


def test_authorize_refuses_a_course_credential_on_a_repo_less_local_realm():
    # A local realm with no remote never reaches provider selection; the
    # credential still rides publish's backend notify, so admission is asked first.
    with pytest.raises(RealmSyncError) as excinfo:
        _authorize(_realm("crs_42"), "publish", None, _credential("course:crs_42"))
    assert excinfo.value.code == "sync_auth_failed"
