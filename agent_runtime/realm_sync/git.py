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
    "_adopt_credential_remote",
    "_adopt_local_remote",
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
    "_merge_remote",
    "_pull_remote_into_repo",
    "_push_was_rejected",
    "_realm_subtree",
    "_redact_text",
    "_refresh_remote_tracking",
    "_scrub_config_values",
    "_sync_repo_path",
    "_sync_state",
]


def _authorize(realm: Realm, action: str, membership: RealmMembershipProvider | None, credential: RealmSyncCredential | None = None) -> None:
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

    from .revocation import refuse_if_revoked

    if credential is not None:
        from ..realm_membership import require_credential_admits

        require_credential_admits(realm, credential)
    refuse_if_revoked(realm, credential_admitted=credential is not None)
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


def _ensure_sync_repo(realm: Realm, *, credential: RealmSyncCredential | None = None) -> Path:
    repo = _sync_repo_path(realm)
    if not (repo.exists() and (repo / ".git").exists()):
        if _looks_like_remote(str(realm.sync_manifest_ref or "")):
            repo.parent.mkdir(parents=True, exist_ok=True)
            _git_clone(str(realm.sync_manifest_ref), repo, extra_config=_credential_git_config(credential))
        else:
            repo.mkdir(parents=True, exist_ok=True)
            _git(repo, "init")
    _adopt_credential_remote(realm, repo, credential)
    _ensure_repo_gitattributes(repo)
    return repo


#: The personal repo's one branch: every machine of the player meets on it.
_LOCAL_REALM_BRANCH = "main"

#: ``AdoptRefused.reason`` -> the ``RealmSyncError`` code a sync verb answers with.
_ADOPT_REFUSAL_CODES = {
    "remote_diverged": "sync_remote_diverged",
    "url_mismatch": "sync_remote_mismatch",
    "fetch_failed": "sync_remote_unreachable",
    "push_failed": "sync_remote_unreachable",
    "not_a_repo": "sync_remote_unreachable",
}


def _adopt_credential_remote(realm: Realm, repo: Path, credential: RealmSyncCredential | None) -> None:
    """A ``local:`` credential's ``git_url`` becomes the realm's ``sync_manifest_ref``
    and the shared local repo's ``origin`` (p10-work §2.6, ``REALM-LOCAL-REMOTE-FROM-CREDENTIAL``).

    The mirror of ``realm_membership.adopt_realms`` for a server-less realm, plus the
    ``git remote add`` a clone never needed: through ``git_remote_adopt.adopt_remote``,
    which pushes ``-u`` into an empty personal repo, takes the remote into an empty local
    one, and merges another machine's unrelated history only when the two touch no common
    path (owner RULED 2026-10-19). Server realms and course credentials never enter (the
    subject check). The ref is moved only when that does not move the repo
    (``_sync_repo_path`` keys an empty or remote ref by ``local``; a pinned local-path ref
    keeps its repo and still gains the remote)."""

    from ..realm_membership import CredentialSubject

    if credential is None or credential.subject is not CredentialSubject.LOCAL_REALM:
        return
    if not credential.admits_realm(realm):
        return
    _adopt_local_remote(realm, repo, credential.git_url,
                        config=(*_REPO_CONFIG, *(_credential_git_config(credential) or ())))


def _adopt_local_remote(realm: Realm, repo: Path, url: str, *, config: Sequence[str]) -> None:
    """``url`` becomes a server-less realm's ``sync_manifest_ref`` and ``repo``'s ``origin``.

    The ONE adoption path: a ``local:`` credential's ``git_url`` and ``harness realm sync
    remote set`` (``remote.set_realm_backup_remote``) both come through here."""

    if str(realm.sync_manifest_ref or "") != url:
        previous = realm.sync_manifest_ref
        realm.sync_manifest_ref = url
        if _sync_repo_path(realm) == repo:
            from ..store import RealmStore

            RealmStore().save(realm, emit_event=False)
        else:
            realm.sync_manifest_ref = previous
    from ..git_remote_adopt import AdoptRefused, adopt_remote

    _align_branch(repo, _LOCAL_REALM_BRANCH)
    try:
        adopt_remote(repo, url, branch=_LOCAL_REALM_BRANCH, config=config, merge_unrelated_if_disjoint=True)
    except AdoptRefused as exc:
        detail = _redact_text(_scrub_config_values(exc.detail, config))
        code = _ADOPT_REFUSAL_CODES.get(exc.reason, "sync_remote_unreachable")
        if code == "sync_remote_unreachable" and "authentication" in detail.lower():
            code = "sync_auth_failed"
        raise RealmSyncError(
            code,
            "Could not adopt the realm's personal sync repository as origin.",
            retryable=exc.reason in {"fetch_failed", "push_failed"},
            safe_details={"adopt_reason": exc.reason, "detail": detail},
        ) from exc


def _align_branch(repo: Path, branch: str) -> None:
    """Name the local branch ``branch`` so ``push``/``@{u}`` match it under
    ``push.default=simple`` (a plain ``git init`` may have named it ``master``)."""

    current = _git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
    if not current or current == branch:
        return
    if _git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False).strip():
        _git(repo, "branch", "-M", branch)
    else:
        _git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")


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


#: git's own words for "the remote moved past you" on a rejected push. The push lane
#: classifies by THESE, never by "a push failed": a remote that is gone, an expired
#: credential and a lost race are three different cures for the operator
#: (RT-REALM-PUBLISH-RACE-SAYS-UNREACHABLE).
_PUSH_REJECTED_TELLS = ("[rejected]", "non-fast-forward", "fetch first", "stale info")


def _push_was_rejected(stderr: str) -> bool:
    """True when ``stderr`` is git refusing a push because the remote has moved on."""

    text = (stderr or "").lower()
    return any(tell in text for tell in _PUSH_REJECTED_TELLS)


def _pull_remote_into_repo(repo: Path, *, credential: RealmSyncCredential | None = None) -> None:
    """``git pull``, past the one untracked file hermes itself writes.

    Fast-forward while the local branch only TRAILS the remote — the ordinary case. A branch
    that has DIVERGED (a publish of ours the remote never took, because another member won
    the race) is merged instead: ``--ff-only`` aborts there, and that abort is what left the
    loser of a publish race stuck, since the one verb that could get it unstuck answered
    ``sync_remote_unreachable`` and the reconciliation every pull applier already runs — the
    inbox/HOLD and the conflict sidecar — was never reached
    (RT-REALM-PUBLISH-RACE-SAYS-UNREACHABLE; owner RULED 2026-11-13). No lock, no retry loop
    and no new reconciliation layer: documents that do not collide merge, and a collision on
    one document is git's conflict, answered with the ``sync_conflict`` the sync verbs
    already carry for exactly that state instead of the network's code.

    ``_ensure_repo_gitattributes`` writes the pin UNTRACKED into a clone made while the remote held
    none (it is committed only by a publish). Once another member publishes theirs, git refuses the
    fast-forward — "untracked working tree files would be overwritten by merge: .gitattributes" —
    and every later pull and publish of that clone fails (RT-REALM-PULL-FAILS-ON-CLONE-MADE-BEFORE-
    FIRST-PUBLISH). The untracked copy is ours to drop when it carries our marker: the incoming
    commit brings the tracked one, and the pin is re-materialized after (a remote that tracks none
    gets the untracked copy back). A foreign untracked ``.gitattributes`` is left for git to refuse.
    """
    path = repo / ".gitattributes"
    try:
        ours = path.is_file() and _REALM_SYNC_GITATTRIBUTES_MARKER in path.read_bytes()
    except OSError:
        ours = False
    if ours and not _git(repo, "ls-files", "--", ".gitattributes", check=False).strip():
        try:
            path.unlink()
        except OSError:
            pass
    try:
        if _git_state(repo)["ahead"]:
            _merge_remote(repo, credential=credential)
        else:
            _git(repo, "pull", "--ff-only", extra_config=_credential_git_config(credential))
    finally:
        _ensure_repo_gitattributes(repo)


def _merge_remote(repo: Path, *, credential: RealmSyncCredential | None = None) -> None:
    """Merge the upstream commit into our diverged branch, or refuse ``sync_conflict``.

    ``-X theirs`` for the documents both sides rewrote, and it is not a policy about whose
    work wins: the sync repo is a TRANSPORT mirror of the member's own store, the pull's
    appliers then reconcile that tree against the store (auto-applying what is safe, holding
    what is not, writing the conflict sidecar) and the next publish rewrites the subtree from
    the store from scratch. Resolving at the git layer instead would stop the pull at a
    manifest every publish rewrites, which is the file this merge collides on first and the
    one nobody can resolve by hand. So a diverged pull lands in exactly the state a pull of a
    merely-behind repo lands in — the design — and the two sides' documents are decided where
    the realm's reconciliation lives (RT-REALM-PUBLISH-RACE-SAYS-UNREACHABLE).

    A conflict ``-X theirs`` cannot resolve (two sides' trees disagree on a path's SHAPE) is
    left in the index: ``sync_conflict``'s ``safe_details.conflicts`` is the operator's list,
    and every later sync verb reads the same state from ``_git_state`` and refuses the same
    way until they have cleared it."""

    _ensure_git_identity(repo)
    proc = run_git(("pull", "--no-rebase", "--no-edit", "-X", "theirs"), repo=repo,
                   config=(*_REPO_CONFIG, *(_credential_git_config(credential) or ())))
    if proc.returncode == 0:
        return
    conflicts = [line.strip() for line in _git(repo, "diff", "--name-only", "--diff-filter=U", check=False).splitlines() if line.strip()]
    if conflicts:
        raise RealmSyncError(
            "sync_conflict",
            "Another member published changes to the same documents; resolve the conflicts in the realm sync repo, then publish again.",
            safe_details={"conflicts": conflicts},
        )
    code = "sync_auth_failed" if "authentication" in (proc.stderr or "").lower() else "sync_remote_unreachable"
    raise RealmSyncError(
        code,
        "git command failed for realm sync.",
        retryable=True,
        safe_details={"git_args": ["pull", "--no-rebase", "-X", "theirs"],
                      "stderr": _redact_text(_scrub_config_values(proc.stderr, _credential_git_config(credential)))},
    )


def _credential_git_config(credential: RealmSyncCredential | None) -> list[str] | None:
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


def _refresh_remote_tracking(repo: Path, *, credential: RealmSyncCredential | None = None) -> dict[str, Any]:
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


#: Config every realm-sync git call carries. ``core.longpaths``: a realm tree nests
#: ``realms/<realm>/store/boards/<board>/cards/<card>.json`` under the sync repo, and
#: Git for Windows refuses a path past MAX_PATH ("Filename too long") without it --
#: measured 2026-10-02, ``git add`` of a 118-char repo root failed the publish. Other
#: platforms' git ignores the key.
_REPO_CONFIG = ("core.longpaths=true",)


def _git(repo: Path, *args: str, check: bool = True, extra_config: Sequence[str] | None = None) -> str:
    proc = run_git(args, repo=repo, config=(*_REPO_CONFIG, *(extra_config or ())))
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
    proc = run_git(["clone", ref, str(repo)], config=(*_REPO_CONFIG, *(extra_config or ())))
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
    # ``file://`` is a remote too: a backup repository on a disk or share. Read as a
    # path it named a sync repo called "file:" (RT-HARNESS-REALM-SET-BACKUP-REMOTE).
    return value.startswith(("http://", "https://", "ssh://", "git@", "file://"))


def _redact_text(text: str) -> str:
    redacted = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text or "")
    home = str(get_hermes_home())
    config = str(get_config_path())
    redacted = redacted.replace(home, "<HERMES_HOME>").replace(config, "<CONFIG>")
    return redacted[-800:]
