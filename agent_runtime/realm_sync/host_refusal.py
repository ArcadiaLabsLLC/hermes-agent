"""A push, fetch or clone the git HOST refused for its authorization: tell the backend, once.

The launcher brokers a realm's git authorization (backend 02 §5); the backend caches the
installation token it hands out. When the owner disconnects the repository (App uninstalled,
repo dropped) the cached token keeps being handed out and github.com keeps refusing it, and
before this every sync answered ``sync_auth_failed`` / ``sync_remote_unreachable`` -- "retry" --
until the cache aged out, up to 44 minutes (backend REALM-GIT-BINDING-DEATH-UNSEEN-WHILE-TOKEN-
CACHED; RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH).

The backend now takes ``POST /realms/{id}/sync/auth-rejected`` (a local realm's credential:
``/me/realms/local:{id}/sync/auth-rejected``) with the credential's ``api_token`` (backend
``603184bc``). It drops the cached token and re-checks the binding:

* ``204`` -- the binding is alive; the next credential the launcher brokers is minted afresh.
  The verb answers ``sync_auth_failed`` (retryable) with ``safe_details.auth_rejected:
  "rebroker"``.
* ``409 realms.git_host_binding_lost`` / ``realms.git_host_unbound`` -- the binding is gone.
  The realm takes the host-state mark (``revocation.mark_realm_revoked``), exactly what the
  launcher records when the credential MINT answers those codes, so the snapshot's
  ``sync.revoked`` carries ``git_host_binding_lost`` and Mission Control shows reconnect, not
  retry. The verb answers ``realm_revoked`` (not retryable).
* anything else (503, 429, no backend) -- the original refusal stands, with
  ``auth_rejected: "unreported"``; the next verb reports again (the backend checks at most once
  a minute per repository, whoever reports).

Reported only for a launcher-brokered credential (a credential-less local backup remote has
no backend to tell) and only once per verb run: the wrapper sits at the verb's edge.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..models import Realm
from .models import RealmSyncError

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

__layer__ = "stores"
__all__ = ["host_refused_auth", "host_refusal_reported", "report_host_refusal"]

#: git's words when the HOST refused the request's authorization (401/403), or answered a
#: repository the token may no longer see as missing (404: GitHub's answer for a private
#: repository the installation dropped). With terminal prompts off (``run_sync_git``) a 401 reads
#: "could not read Username ... terminal prompts disabled"; with a helper it is "Authentication
#: failed".
_HOST_REFUSAL_TELLS = (
    "authentication failed",
    "invalid username or password",
    "could not read username",
    "terminal prompts disabled",
    "returned error: 401",
    "returned error: 403",
    "write access to repository not granted",
    "permission to ",
    "repository not found",
)

#: Backend refusal codes on the report -> the host-state mark they are.
_REPORT_MARKS = ("realms.git_host_binding_lost", "realms.git_host_unbound")


def host_refused_auth(exc: RealmSyncError) -> bool:
    """True when ``exc`` is a git call the host refused for its authorization."""

    details = exc.safe_details or {}
    text = f"{details.get('stderr') or ''}\n{details.get('detail') or ''}".lower()
    return any(tell in text for tell in _HOST_REFUSAL_TELLS)


def report_host_refusal(realm: Realm, credential: RealmSyncCredential | None, exc: RealmSyncError) -> RealmSyncError:
    """The refusal the verb answers with after telling the backend; ``exc`` itself when there was
    nothing to report (not a host auth refusal, no brokered credential, already reported)."""

    if credential is None or exc.safe_details.get("auth_rejected") or not host_refused_auth(exc):
        return exc
    from ..realm_membership import report_git_auth_rejected

    try:
        status, payload = report_git_auth_rejected(credential, realm)
    except RealmSyncError:
        status, payload = 0, None
    code = str((payload or {}).get("code") or "") if isinstance(payload, dict) else ""
    if status in {200, 204}:
        return RealmSyncError(
            "sync_auth_failed",
            "The git host refused this realm's credential; the next sync gets a fresh one.",
            retryable=True,
            safe_details={**exc.safe_details, "auth_rejected": "rebroker"},
        )
    if status == 409 and code in _REPORT_MARKS:
        from .revocation import BACKEND_REFUSAL_REASONS, REALM_REVOKED_CODE, mark_realm_revoked

        mark = mark_realm_revoked(realm, BACKEND_REFUSAL_REASONS[code])
        return RealmSyncError(
            REALM_REVOKED_CODE,
            "The realm's repository was disconnected; sync is paused until it is reconnected. Local data is kept.",
            retryable=False,
            safe_details={"revoked_reason": mark.get("reason"), "host_state": True, "auth_rejected": "binding_lost"},
        )
    exc.safe_details = {**exc.safe_details, "auth_rejected": "unreported", "report_status": status}
    return exc


@contextmanager
def host_refusal_reported(realm: Realm, credential: RealmSyncCredential | None) -> Iterator[None]:
    """Run a verb body; a host auth refusal escaping it is reported first (``report_host_refusal``)."""

    try:
        yield
    except RealmSyncError as exc:
        answer = report_host_refusal(realm, credential, exc)
        if answer is exc:
            raise
        raise answer from exc

