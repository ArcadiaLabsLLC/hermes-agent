"""The realm sync repository on disk: authorization, clone/init, git plumbing, redaction.

Every subprocess realm sync runs goes through ``_git`` / ``_git_clone`` here, and
the credential's ``-c`` config never leaves this module unscrubbed.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hermes_constants import get_config_path, get_hermes_home

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

from .. import paths
from ..git_cmd import run_git
from ..models import Realm
from ..redaction import SECRET_ASSIGNMENT_RE
from .models import (
    RealmMembershipProvider,
    RealmSyncError,
    _REALM_SYNC_GITATTRIBUTES,
    _REALM_SYNC_GITATTRIBUTES_MARKER,
)

__layer__ = "stores"
__all__ = [
    "_authorize",
    "_credential_git_config",
    "_ensure_git_identity",
    "_ensure_repo_gitattributes",
    "_ensure_sync_repo",
    "_git",
    "_git_clone",
    "_git_state",
    "_has_remote",
    "_looks_like_remote",
    "_realm_subtree",
    "_redact_text",
    "_refresh_remote_tracking",
    "_scrub_config_values",
    "_sync_repo_path",
    "_sync_state",
]


def _authorize(realm: Realm, action: str, membership: RealmMembershipProvider | None, credential: "RealmSyncCredential | None" = None) -> None:
    """Raise the typed refusal when this realm+action is not permitted.

    Unchanged for the two WRITE verbs: ``publish_realm_sync`` and
    ``pull_realm_sync`` call it first and let it refuse them WHOLE, because
    every byte they touch is a realm-wide assertion and there is no half of
    either that a denied member is entitled to run.

    ``realm_sync_status`` is the exception, and it is not a weakening of this
    gate: it CATCHES the refusal and applies it to the remote half only (the
    clone, the fetch, and therefore the freshness of ahead/behind), answering
    the credential-free local half with ``remote_checked: false`` and this
    error's code. See that function for the floor — no local repo, no degrade.
    """

    if membership is None:
        if not _looks_like_remote(str(realm.sync_manifest_ref or "")):
            membership = RealmMembershipProvider()
        else:
            # Stage 43 fail-closed selection: remote server-bound realms require the
            # backend-authoritative provider (credential-backed); server-less and
            # local-path realms keep the local allow stub unchanged.
            from ..realm_membership import select_membership_provider

            membership = select_membership_provider(realm, credential)
    decision = membership.authorize(realm, action)
    if not decision.allowed:
        raise RealmSyncError(decision.code or "membership_denied", decision.message or "Realm membership does not allow this sync action.")


def _ensure_sync_repo(realm: Realm, *, credential: "RealmSyncCredential | None" = None) -> Path:
    repo = _sync_repo_path(realm)
    if repo.exists() and (repo / ".git").exists():
        _ensure_repo_gitattributes(repo)
        return repo
    if _looks_like_remote(str(realm.sync_manifest_ref or "")):
        repo.parent.mkdir(parents=True, exist_ok=True)
        _git_clone(str(realm.sync_manifest_ref), repo, extra_config=_credential_git_config(credential))
    else:
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init")
    _ensure_repo_gitattributes(repo)
    return repo


def _ensure_repo_gitattributes(repo: Path) -> None:
    """Materialize the LF line-ending pin at the realm sync repo root.

    Idempotent: rewrites only the file we manage (identified by our marker) and
    respects any foreign ``.gitattributes`` a repo already carries. It is written
    here but committed by ``publish_realm_sync`` (it rides the same publish lane
    as the realm subtree). Best-effort — a write failure never fails the sync
    verb (the publisher still canonicalizes bytes to LF regardless)."""
    path = repo / ".gitattributes"
    desired = _REALM_SYNC_GITATTRIBUTES.encode("utf-8")
    try:
        if path.exists():
            existing = path.read_bytes()
            if existing == desired:
                return
            if _REALM_SYNC_GITATTRIBUTES_MARKER not in existing:
                return  # respect a foreign .gitattributes; only manage our own
        path.write_bytes(desired)
    except OSError:
        return


def _credential_git_config(credential: "RealmSyncCredential | None") -> list[str] | None:
    """Per-invocation git auth config (Decision 4): rendered as ``git -c`` args,
    never written to ``.git/config`` and never surfaced in safe_details/logs."""
    if credential is None:
        return None
    return credential.git_extra_config()


def _sync_repo_path(realm: Realm) -> Path:
    ref = str(realm.sync_manifest_ref or "").strip()
    if ref and not _looks_like_remote(ref):
        return Path(ref).expanduser()
    key = paths.safe_path_token(realm.server_id or "local")
    return paths.realm_sync_root() / key


def _realm_subtree(repo: Path, realm_id: str) -> Path:
    return repo / "realms" / paths.safe_path_token(realm_id)


def _git_state(repo: Path) -> dict[str, Any]:
    conflicts = [line.strip() for line in _git(repo, "diff", "--name-only", "--diff-filter=U", check=False).splitlines() if line.strip()]
    ahead = behind = 0
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False).strip()
    if upstream:
        counts = _git(repo, "rev-list", "--left-right", "--count", "HEAD...@{u}", check=False).split()
        if len(counts) == 2:
            ahead, behind = int(counts[0]), int(counts[1])
    dirty = bool(_git(repo, "status", "--porcelain", check=False).strip())
    return {"ahead": ahead, "behind": behind, "conflicts": conflicts, "dirty": dirty}


def _sync_state(git: dict[str, Any]) -> str:
    if git["conflicts"]:
        return "conflict"
    if git["behind"]:
        return "behind"
    if git["ahead"] or git["dirty"]:
        return "ahead"
    return "in_sync"


def _has_remote(repo: Path) -> bool:
    return bool(_git(repo, "remote", check=False).strip())


def _refresh_remote_tracking(repo: Path, *, credential: "RealmSyncCredential | None" = None) -> dict[str, Any]:
    """Best-effort ``git fetch`` so ``_git_state``'s ahead/behind answer against
    the remote AS IT IS, not as the last pull/publish left it cached.

    Returns a typed row, never raises: ``checked`` is True only when a remote
    exists and the fetch succeeded; ``error`` carries the ``RealmSyncError``
    code (``sync_auth_failed`` / ``sync_remote_unreachable``) when it did not,
    and stays None for a repo with no remote (nothing to check is not a
    failure). Callers that must hard-fail on remote problems (push) keep their
    own typed errors — this helper exists for the read paths, where an offline
    box still deserves a local answer.
    """

    if not _has_remote(repo):
        return {"checked": False, "error": None}
    try:
        _git(repo, "fetch", extra_config=_credential_git_config(credential))
    except RealmSyncError as exc:
        return {"checked": False, "error": exc.code}
    return {"checked": True, "error": None}


def _git(repo: Path, *args: str, check: bool = True, extra_config: Sequence[str] | None = None) -> str:
    proc = run_git(args, repo=repo, config=extra_config)
    if check and proc.returncode != 0:
        code = "sync_auth_failed" if "authentication" in (proc.stderr or "").lower() else "sync_remote_unreachable"
        # safe_details carries the plain subcommand args only — the -c config
        # pairs (which can hold an Authorization header) are never included,
        # and their values are scrubbed from stderr before redaction.
        raise RealmSyncError(
            code,
            "git command failed for realm sync.",
            retryable=True,
            safe_details={"git_args": list(args), "stderr": _redact_text(_scrub_config_values(proc.stderr, extra_config))},
        )
    return proc.stdout


def _git_clone(ref: str, repo: Path, *, extra_config: Sequence[str] | None = None) -> None:
    proc = run_git(["clone", ref, str(repo)], config=extra_config)
    if proc.returncode != 0:
        code = "sync_auth_failed" if "authentication" in (proc.stderr or "").lower() else "sync_remote_unreachable"
        raise RealmSyncError(
            code,
            "Could not clone realm sync repository.",
            retryable=True,
            safe_details={"stderr": _redact_text(_scrub_config_values(proc.stderr, extra_config))},
        )


def _scrub_config_values(text: str, extra_config: Sequence[str] | None) -> str:
    scrubbed = text or ""
    for pair in extra_config or []:
        _key, _sep, value = str(pair).partition("=")
        if value.strip():
            scrubbed = scrubbed.replace(value, "[redacted]")
    return scrubbed


def _ensure_git_identity(repo: Path) -> None:
    if not _git(repo, "config", "user.email", check=False).strip():
        _git(repo, "config", "user.email", "realm-sync@localhost")
    if not _git(repo, "config", "user.name", check=False).strip():
        _git(repo, "config", "user.name", "Hermes Realm Sync")


def _looks_like_remote(value: str) -> bool:
    return value.startswith(("http://", "https://", "ssh://", "git@"))


def _redact_text(text: str) -> str:
    redacted = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text or "")
    home = str(get_hermes_home())
    config = str(get_config_path())
    redacted = redacted.replace(home, "<HERMES_HOME>").replace(config, "<CONFIG>")
    return redacted[-800:]
