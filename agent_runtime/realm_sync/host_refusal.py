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

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..models import Realm
from ..redaction import scrub_secret_values
from .models import RealmSyncError

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

__layer__ = "stores"
__all__ = ["host_refusal_reported", "host_refusal_status", "host_refused_auth", "report_host_refusal"]

#: The HTTP status the host answered, as git reports it: "The requested URL returned error: 403".
_HOST_STATUS_RE = re.compile(r"returned error:\s*(\d{3})\b", re.IGNORECASE)

#: git's own error TYPES for a host answer whose status git does not print, each with the status it
#: stands for. With terminal prompts off (``run_sync_git``) a 401 is git's refused credential prompt
#: ("could not read Username ... terminal prompts disabled"); through a credential helper it is git's
#: "Authentication failed for <url>". GitHub answers a private repository the installation dropped
#: as missing (404, "remote: Repository not found") and a token without write access with "remote:
#: Permission to <repo> denied" / "Write access to repository not granted" beside a 403.
_GIT_ERROR_STATUS = (
    (re.compile(r"terminal prompts disabled", re.IGNORECASE), 401),
    (re.compile(r"^fatal: authentication failed for ", re.IGNORECASE | re.MULTILINE), 401),
    (re.compile(r"^remote: (?:permission to \S+ denied|write access to repository not granted)", re.IGNORECASE | re.MULTILINE), 403),
    (re.compile(r"^remote: repository not found", re.IGNORECASE | re.MULTILINE), 404),
)

#: The host statuses that refuse the request's authorization (404: a repository the token no
#: longer sees).
_REFUSAL_STATUSES = frozenset({401, 403, 404})

#: Backend refusal codes on the report -> the host-state mark they are.
_REPORT_MARKS = ("realms.git_host_binding_lost", "realms.git_host_unbound")


def host_refusal_status(exc: RealmSyncError) -> int | None:
    """The HTTP status the host answered ``exc``'s git call with, when git's report names one --
    printed, or implied by git's own error type (``_GIT_ERROR_STATUS``); ``None`` otherwise.

    Read from the VALUE-scrubbed report (``agent_runtime.redaction``): a status is decided by the
    host's answer, never by a word in the text."""

    details = exc.safe_details or {}
    text = scrub_secret_values(f"{details.get('stderr') or ''}\n{details.get('detail') or ''}")
    match = _HOST_STATUS_RE.search(text)
    if match:
        return int(match.group(1))
    return next((status for pattern, status in _GIT_ERROR_STATUS if pattern.search(text)), None)


def host_refused_auth(exc: RealmSyncError) -> bool:
    """True when ``exc`` is a git call the host refused for its authorization (401/403/404)."""

    return host_refusal_status(exc) in _REFUSAL_STATUSES


def _scrubbed(details: dict) -> dict:
    """``details`` with git's report VALUE-scrubbed (``agent_runtime.redaction``) before an answer carries it."""

    return {key: scrub_secret_values(value) if key in {"stderr", "detail"} and isinstance(value, str) else value
            for key, value in details.items()}


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
            safe_details={**_scrubbed(exc.safe_details), "auth_rejected": "rebroker"},
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
    exc.safe_details = {**_scrubbed(exc.safe_details), "auth_rejected": "unreported", "report_status": status}
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

