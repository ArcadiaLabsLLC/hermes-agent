"""The realm sync repository on disk: authorization, clone/init, git plumbing, redaction.

Realm sync asks git for NAMED STEPS (``git_port.SyncGit``) through ``sync_git(repo)``,
which hands back the backend ``sync_git_backend()`` picks for this call. The binary
backend (``git_binary``) runs every subprocess through ``_git`` / ``_git_clone`` here, and
the credential's ``-c`` config never leaves this module unscrubbed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hermes_constants import get_config_path, get_hermes_home

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

from .. import paths
from ..git_cmd import run_git
from ..models import Realm
from ..redaction import SECRET_ASSIGNMENT_RE
from .git_port import SyncGit
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
    "_ensure_repo_gitattributes",
    "_ensure_sync_repo",
    "_git",
    "_git_clone",
    "_git_failure",
    "_git_state",
    "_has_remote",
    "_looks_like_remote",
    "_merge_remote",
    "_pull_remote_into_repo",
    "_push_was_rejected",
    "_realm_subtree",
    "_redact_text",
    "_refresh_remote_tracking",
    "_retire_shared_clone",
    "_scrub_config_values",
    "_sync_repo_path",
    "_sync_state",
    "SYNC_IDENTITY",
    "SyncGitBackend",
    "run_sync_git",
    "sync_git",
    "sync_git_backend",
]


class SyncGitBackend(Enum):
    """Which git answers realm sync's steps (``git_port.SyncGit``)."""

    #: The host's git program (``git_binary``): every desktop.
    BINARY = "binary"
    #: The pure-Python git a phone carries (plan phone-realm-sync-dulwich-2026-11-16).
    DULWICH = "dulwich"


def sync_git_backend() -> SyncGitBackend:
    """The ONE answer to "which git syncs realms here": config ``realm_sync.git_backend``, read per call.

    Never a sniff of the host — not ``shutil.which``, not a failing git, not the phone's loud ``git_cmd``
    stand-in: a desktop whose git is missing keeps failing loudly, and only a profile that says
    ``dulwich`` (the bundled phone's) gets the pure-Python git. Absent, empty or an unreadable config is
    ``binary`` (today's); a value that names no backend refuses ``sync_backend_unknown``, never falls back."""

    from hermes_cli import config as _config

    try:
        value = _config.cfg_get(_config.load_config_readonly(), "realm_sync", "git_backend", default=None)
    except Exception:  # health: allow BLE001 -- an unreadable config is today's backend, as every switch reads it
        return SyncGitBackend.BINARY
    if value is None or str(value).strip() == "":
        return SyncGitBackend.BINARY
    try:
        return SyncGitBackend(str(value).strip().lower())
    except ValueError:
        raise RealmSyncError(
            "sync_backend_unknown",
            "Realm sync is configured with a git backend this version does not know.",
            safe_details={"realm_sync.git_backend": str(value)[:40],
                          "known": [backend.value for backend in SyncGitBackend]},
        ) from None


def sync_git(repo: Path) -> SyncGit:
    """The realm-sync port for the clone at ``repo``, answered by this call's backend."""

    backend = sync_git_backend()
    if backend is SyncGitBackend.BINARY:
        from .git_binary import BinarySyncGit

        return BinarySyncGit(repo)
    if backend is SyncGitBackend.DULWICH:
        from .git_dulwich import DulwichSyncGit

        return DulwichSyncGit(repo)
    raise RealmSyncError("sync_backend_unknown", f"Realm sync has no git backend {backend.value!r} on this device.")


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
    _take_server_credential_url(realm, credential)
    repo = _sync_repo_path(realm)
    if not (repo.exists() and (repo / ".git").exists()):
        if _looks_like_remote(str(realm.sync_manifest_ref or "")):
            repo.parent.mkdir(parents=True, exist_ok=True)
            sync_git(repo).clone(str(realm.sync_manifest_ref), credential)
        else:
            repo.mkdir(parents=True, exist_ok=True)
            sync_git(repo).init()
    _adopt_credential_remote(realm, repo, credential)
    _follow_server_repository(realm, repo, credential)
    _ensure_repo_gitattributes(repo)
    return repo


def _take_server_credential_url(realm: Realm, credential: RealmSyncCredential | None) -> None:
    """A server realm's brokered credential names the repository it syncs with today: its ``git_url`` becomes
    the realm's ``sync_manifest_ref`` (a re-adopt writes the same). The ref of a remote is not the clone's
    key (``_sync_repo_path`` keys it by the realm's id), so the clone stays where it is and follows
    (``_follow_server_repository``). A pinned local-path ref is the member's own and is left alone."""

    if not realm.server_id or credential is None or not credential.admits_realm(realm):
        return
    url, ref = credential.git_url, str(realm.sync_manifest_ref or "")
    if not _looks_like_remote(url) or ref == url or (ref and not _looks_like_remote(ref)):
        return
    realm.sync_manifest_ref = url
    from ..store import RealmStore

    RealmStore().save(realm, emit_event=False)


def _follow_server_repository(realm: Realm, repo: Path, credential: RealmSyncCredential | None) -> None:
    """A server realm whose repository moved: its clone follows to the new one, keeping unpublished work.

    The clone is made once, from the ``git_url`` of the day, and its ``origin`` was never looked at again: a
    server that connected another repository (``subject_git_host`` connect/disconnect announce nothing) kept
    every member publishing into, and pulling from, the old one (backend REALM-OWN-REPO-CHANGE-NOT-ANNOUNCED,
    its hermes half). A clone whose ``origin`` names another repository than the realm's ref (which
    ``_take_server_credential_url`` has already moved) is re-pointed through ``git_remote_adopt.adopt_remote``:
    an empty new repository takes the clone's history (unpublished commits included), a new repository that
    shares it is simply tracked, an unrelated one is merged only when the two touch no common path, and
    otherwise the verb refuses ``sync_remote_diverged`` with nothing lost (the old ``origin`` is put back, so
    the next verb tries again). Branches and the working tree are never reset; only ``origin`` and its
    tracking refs are replaced.

    It never PUSHES (RT-REALM-SYNC-PULL-PUBLISHES-INTO-A-MOVED-REPO, seen live 2026-11-14): every verb runs it
    — a status read ("Check now"), a dry-run Pull and a Pull, each authorised as that verb, never as publish —
    and an empty new repository used to be seeded here with the member's unpublished commits, under "Ask me
    first" too. The clone now only tracks the new ``origin``; its commits read ``ahead`` (``_git_state``) and
    reach the new repository through the member's own Publish, an empty new repository included (owner RULED
    2026-11-14: a Pull, a status read and a dry run never push; following a move only re-points and fetches)."""

    if not realm.server_id:
        return
    url = str(realm.sync_manifest_ref or "")
    if not _looks_like_remote(url):
        return
    git = sync_git(repo)
    origin = git.remote_url("origin")
    if not origin:
        return  # never a server clone (a pinned or re-keyed repo): not this function's to give a remote
    if origin == url:
        return
    branch = git.current_branch() or _LOCAL_REALM_BRANCH
    # ``remote_remove`` drops the OLD repository's tracking refs with it: a stale ``origin/<branch>`` left
    # behind would read as the new repository's tip.
    git.remote_remove("origin")
    from ..git_remote_adopt import AdoptRefused, adopt_remote

    config = _credential_git_config(credential)
    try:
        adopt_remote(repo, url, branch=branch, merge_unrelated_if_disjoint=True, push_into_empty=False,
                     git=git, auth=credential)
    except AdoptRefused as exc:
        # Put the old ``origin`` back, so the next verb sees the move again and retries it.
        git.remote_remove("origin", missing_ok=True)
        try:
            git.remote_add("origin", origin)
        except RealmSyncError:
            pass
        detail = _redact_text(_scrub_config_values(exc.detail, config))
        code = _ADOPT_REFUSAL_CODES.get(exc.reason, "sync_remote_unreachable")
        if code == "sync_remote_unreachable" and "authentication" in detail.lower():
            code = "sync_auth_failed"
        raise RealmSyncError(
            code,
            "The realm's repository moved, and this machine's copy could not follow it yet.",
            retryable=exc.reason in {"fetch_failed", "push_failed"},
            safe_details={"adopt_reason": exc.reason, "detail": detail, "stderr": detail},
        ) from exc


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
    and the realm's own sync repo's ``origin`` (p10-work §2.6, ``REALM-LOCAL-REMOTE-FROM-CREDENTIAL``).

    The mirror of ``realm_membership.adopt_realms`` for a server-less realm, plus the
    ``git remote add`` a clone never needed: through ``git_remote_adopt.adopt_remote``,
    which leaves an empty personal repo empty for Publish to fill, takes the remote into an empty local
    one, and merges another machine's unrelated history only when the two touch no common
    path (owner RULED 2026-10-19). Server realms and course credentials never enter (the
    subject check). The ref is moved only when that does not move the repo
    (``_sync_repo_path`` keys an empty or remote ref by the realm's id; a pinned local-path ref
    keeps its repo and still gains the remote)."""

    from ..realm_membership import CredentialSubject

    if credential is None or credential.subject is not CredentialSubject.LOCAL_REALM:
        return
    if not credential.admits_realm(realm):
        return
    _adopt_local_remote(realm, repo, credential.git_url, credential=credential)


def _adopt_local_remote(realm: Realm, repo: Path, url: str, *, credential: RealmSyncCredential | None = None) -> None:
    """``url`` becomes a server-less realm's ``sync_manifest_ref`` and ``repo``'s ``origin``.

    The ONE adoption path: a ``local:`` credential's ``git_url`` and ``harness realm sync
    remote set`` (``remote.set_realm_backup_remote``) both come through here.

    It never PUSHES (RT-LOCAL-REALM-STATUS-READ-PUSHES-INTO-AN-EMPTY-BACKUP-REPO; owner RULED 2026-11-14,
    superseding the 2026-10-19 seeding allowance): every verb runs it — a status read ("Check now"), a dry-run
    Pull, a Pull, a remote set — and an EMPTY backup repo is filled only by the member's own Publish. The
    clone's unpushed commits read ``ahead`` (``_git_state``'s no-upstream arm) until then."""

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
    config = _credential_git_config(credential)
    try:
        adopt_remote(repo, url, branch=_LOCAL_REALM_BRANCH, merge_unrelated_if_disjoint=True, push_into_empty=False,
                     git=sync_git(repo), auth=credential)
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

    git = sync_git(repo)
    current = git.current_branch()
    if not current or current == branch:
        return
    git.rename_branch(branch)


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
    git = sync_git(repo)
    if ours and not git.is_tracked(".gitattributes"):
        try:
            path.unlink()
        except OSError:
            pass
    try:
        if _git_state(repo)["ahead"]:
            _merge_remote(repo, credential=credential)
        else:
            git.pull_fast_forward(credential)
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

    merged = sync_git(repo).merge_remote_theirs(credential)
    if merged.conflicts:
        raise RealmSyncError(
            "sync_conflict",
            "Another member published changes to the same documents; resolve the conflicts in the realm sync repo, then publish again.",
            safe_details={"conflicts": list(merged.conflicts)},
        )


def _credential_git_config(credential: RealmSyncCredential | None) -> list[str] | None:
    """Per-invocation git auth config (Decision 4): rendered as ``git -c`` args,
    never written to ``.git/config`` and never surfaced in safe_details/logs."""
    if credential is None:
        return None
    return credential.git_extra_config()


def _sync_repo_path(realm: Realm) -> Path:
    """The realm's OWN clone (RT-REALM-SYNC-ONE-CLONE-PER-REALM), or the member's pinned local-path repo.

    It used to be keyed by ``realm.server_id or "local"``: every realm of a server shared one working
    tree and every server-less realm shared ``local``, so a second realm bound to a different
    repository was refused ``sync_remote_mismatch``. The first lookup after the upgrade carries the
    old shared clone over (``_carry_shared_clone``), so every verb -- status and history included --
    finds the realm's unpublished work where it now lives."""

    ref = str(realm.sync_manifest_ref or "").strip()
    if ref and not _looks_like_remote(ref):
        return Path(ref).expanduser()
    repo = paths.realm_sync_clone_dir(realm.id)
    if not (repo / ".git").exists():
        _carry_shared_clone(realm, repo)
    legacy = _legacy_shared_clone(realm)
    if (legacy / ".git").is_dir():
        _retire_shared_clone(legacy)
    return repo


def _legacy_shared_clone(realm: Realm) -> Path:
    """Where the realm's clone lived while clones were shared: ``realm_sync/<server or "local">``."""

    return paths.realm_sync_root() / paths.safe_path_token(realm.server_id or paths.REALM_SYNC_LEGACY_LOCAL_CLONE)


def _carry_shared_clone(realm: Realm, repo: Path) -> None:
    """COPY the old shared clone to the realm's own place, once, when it is this realm's to inherit.

    A copy, never a move, and the old clone is never deleted here: several realms may have unpublished
    commits or files in it, and each one's first lookup takes its own copy, keeping everything (review
    batch 15's recommendation). ``_retire_shared_clone`` removes it once every realm it holds has its copy. Only a realm whose subtree the shared clone holds inherits it. Skipped -- the
    realm clones fresh instead -- when the shared clone's ``origin``
    is a repository other than the one this realm names, which is exactly the case a shared tree
    could not serve. Best effort: a copy that fails is removed, and the realm clones fresh."""

    legacy = _legacy_shared_clone(realm)
    if not (legacy / ".git").is_dir() or repo.exists() or not _realm_subtree(legacy, realm.id).exists():
        return  # nothing of this realm's is there: a realm made since clones are its own starts clean
    ref = str(realm.sync_manifest_ref or "").strip()
    origin = sync_git(legacy).remote_url("origin") or ""
    if origin and _looks_like_remote(ref) and origin != ref:
        return
    try:
        repo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(legacy, repo, symlinks=True)
    except OSError:
        shutil.rmtree(repo, ignore_errors=True)


def _retire_shared_clone(legacy: Path) -> bool:
    """Remove an old shared clone once nothing in it is left only there (RT-REALM-SYNC-OLD-SHARED-CLONES-STAY-ON-DISK).

    Removed only when EVERY realm whose subtree it holds has its own clone, each of those clones already
    holds the shared clone's last commit (the copy took it, or a later publish built on it), and the shared
    clone has no uncommitted or untracked file (hermes's own untracked ``.gitattributes`` pin aside). A
    shared clone with a realm still to carry it over, a commit some realm's clone lacks, a file never
    committed, or a git that cannot answer is kept as it is -- the next lookup asks again. Returns whether
    it was removed."""

    realms = legacy / "realms"
    held = [entry.name for entry in realms.iterdir() if entry.is_dir()] if realms.is_dir() else []
    git = sync_git(legacy)
    commit = git.resolve("HEAD")
    if commit is None:
        return False
    try:
        status = git.changed(untracked_all=True)
    except RealmSyncError:
        return False
    for entry in status:
        if entry.untracked and entry.path == ".gitattributes":
            try:
                if _REALM_SYNC_GITATTRIBUTES_MARKER in (legacy / ".gitattributes").read_bytes():
                    continue
            except OSError:
                pass
        return False  # a file only this clone has
    for token in held:
        own = paths.realm_sync_root() / paths.REALM_SYNC_CLONES_DIRNAME / token
        if not (own / ".git").exists():
            return False  # this realm has not taken its copy yet
        if not sync_git(own).is_ancestor(commit, "HEAD"):
            return False  # its clone lacks the shared clone's last commit
    from utils import rmtree_readonly

    try:
        rmtree_readonly(legacy)
    except OSError:
        return False
    return True


def _realm_subtree(repo: Path, realm_id: str) -> Path:
    return repo / "realms" / paths.safe_path_token(realm_id)


def _git_state(repo: Path) -> dict[str, Any]:
    """``RepoState`` in the envelope's shape. With no upstream but a remote (a clone that followed its realm
    into an EMPTY new repository and pushed nothing, ``_follow_server_repository``) the commits no remote
    holds read ``ahead``, so the next Publish carries them even with no new bytes
    (RT-REALM-SYNC-PULL-PUBLISHES-INTO-A-MOVED-REPO)."""

    return sync_git(repo).state().as_dict()


def _sync_state(git: dict[str, Any]) -> str:
    if git["conflicts"]:
        return "conflict"
    if git["behind"]:
        return "behind"
    if git["ahead"] or git["dirty"]:
        return "ahead"
    return "in_sync"


def _has_remote(repo: Path) -> bool:
    return bool(sync_git(repo).remotes())


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
        return {"checked": False, "error": None, "failure": None}
    try:
        sync_git(repo).fetch(credential)
    except RealmSyncError as exc:
        # ``failure``: the refusal itself, so the status read can report a host auth refusal
        # (``host_refusal``) -- never part of an envelope.
        return {"checked": False, "error": exc.code, "failure": exc}
    return {"checked": True, "error": None, "failure": None}


#: Config every realm-sync git call carries. ``core.longpaths``: a realm tree nests
#: ``realms/<realm>/store/boards/<board>/cards/<card>.json`` under the sync repo, and
#: Git for Windows refuses a path past MAX_PATH ("Filename too long") without it --
#: measured 2026-10-02, ``git add`` of a 118-char repo root failed the publish. Other
#: platforms' git ignores the key.
#: ``SYNC_IDENTITY``: the one name every realm-sync commit (and merge) carries, on every machine
#: (RT-REALM-SYNC-COMMIT-LEAKS-MEMBER-EMAIL). It used to be written to the repo's config only when
#: ``git config user.email`` answered nothing -- a lookup that reads the GLOBAL config too -- so on a
#: machine whose user had a git identity the publish carried THAT PERSON'S name and email into a
#: repository other members read and that may go public later. A ``-c`` pair beats every config
#: file, and ``run_sync_git`` drops the ``GIT_AUTHOR_*``/``GIT_COMMITTER_*`` variables that would
#: beat the pair. Who published a change is a commit trailer instead (owner RULED 2026-11-14 on
#: RT-REALM-SYNC-COMMITS-NAME-NOBODY: never an email or a real name).
SYNC_IDENTITY = ("user.name=Hermes Realm Sync", "user.email=realm-sync@localhost")
_REPO_CONFIG = ("core.longpaths=true", *SYNC_IDENTITY)
_IDENTITY_ENV = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")


def run_sync_git(args: Sequence[str], **run_kwargs: Any) -> subprocess.CompletedProcess[str]:
    """``run_git`` for a realm sync repository: the caller's identity variables never reach git.

    An exported ``GIT_AUTHOR_EMAIL`` outranks ``-c user.email`` and every config file, so the
    ``SYNC_IDENTITY`` pair alone would still let a member's own address into the history."""

    env = dict(run_kwargs.pop("env", None) or os.environ)
    for name in _IDENTITY_ENV:
        env.pop(name, None)
    # A host that refuses the brokered Authorization (401) makes git ask for a username. No one
    # answers a realm sync's prompt: it must fail, so the refusal is reported
    # (``host_refusal``, RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH) instead of hanging on a terminal.
    env["GIT_TERMINAL_PROMPT"] = "0"
    return run_git(args, env=env, **run_kwargs)


def _git(repo: Path, *args: str, check: bool = True, extra_config: Sequence[str] | None = None) -> str:
    proc = run_sync_git(args, repo=repo, config=(*_REPO_CONFIG, *(extra_config or ())))
    if check and proc.returncode != 0:
        raise _git_failure(list(args), proc, extra_config)
    return proc.stdout


def _git_failure(git_args: list[str], proc: subprocess.CompletedProcess[str],
                 extra_config: Sequence[str] | None) -> RealmSyncError:
    """The typed refusal for a git step that failed. ``safe_details`` carries the plain subcommand args
    only — the -c config pairs (which can hold an Authorization header) are never included, and their
    values are scrubbed from stderr before redaction."""

    code = "sync_auth_failed" if "authentication" in (proc.stderr or "").lower() else "sync_remote_unreachable"
    return RealmSyncError(
        code,
        "git command failed for realm sync.",
        retryable=True,
        safe_details={"git_args": git_args, "stderr": _redact_text(_scrub_config_values(proc.stderr, extra_config))},
    )


def _git_clone(ref: str, repo: Path, *, extra_config: Sequence[str] | None = None) -> None:
    proc = run_sync_git(["clone", ref, str(repo)], config=(*_REPO_CONFIG, *(extra_config or ())))
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
