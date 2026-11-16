"""``publish_folder`` — push a ready-made folder, as it is, to a realm's publishing repository.

RT-REALM-PUBLISHING-PUSHES-A-FOLDER (slice S3). The order is the argument:

1. the folder and branch are read (``invalid_request``);
2. a publishing repository must be connected — the caller hands its credential, minted by the backend's
   ``POST /api/realms/{id}/publishing-host/credential`` (REALM-PUBLISHING-CREDENTIAL); with none,
   ``publishing_not_connected``. A credential for anything else (the realm's WORKING repository, a course,
   another realm) is ``sync_auth_failed``: pushing a site into the working repository would overwrite the
   team's data;
3. the backend is asked, right before the push, whether this member may publish the realm
   (``realm_membership.ask_backend_permission`` -> ``sync_permission(…, "publish")``, the one authority —
   never re-derived here; a member whose role went away since the mint is refused);
4. the publishing clone (``paths.realm_publishing_clone_dir``, never the sync clone) is pointed at the
   repository, its branch tip fetched, its working tree replaced by the folder plus ``.nojekyll`` (Pages then
   serves the files without a Jekyll build, plan §3), committed when anything differs, and pushed as a
   fast-forward of the branch.

The folder is never written to and nothing in it is generated or renamed. What goes up is ONE list, built once
by :func:`site_paths` and used for the dry run's ``paths``, the count and the copy alike
(RT-REALM-PUBLISHING-PUBLISHES-SECRETS-IN-THE-FOLDER, owner RULED 2026-11-16 "ah okay cool yes"):

* every hidden entry is left out — a file or folder whose name starts with ``.`` (``.env``, ``.git``,
  ``.ssh``, …), at any depth. A site that needs ``.well-known/`` loses it too (documented, not worked);
* the patterns in the folder's own :data:`IGNORE_FILE` are left out (its syntax: :func:`_read_ignore_file`);
* what is still left and looks like a secret refuses the whole publish with ``sync_secret_excluded``, naming
  the files in ``safe_details.paths``, before the clone is touched (dry run included): realm sync's own
  predicates (``realm_sync.families.is_secretish_path`` — ``SECRET_PATH_MARKERS`` — and
  ``realm_sync.pull.file_contains_secret_assignment``, the token-shaped text) plus the publishing name
  patterns :data:`SECRET_NAME_PATTERNS` and a private-key block (:data:`_PRIVATE_KEY_BLOCK`).

A push (not a dry run) goes up only as the list the player confirmed (RT-REALM-PUBLISHING-PUSH-SENDS-ONLY-THE-
CONFIRMED-LIST; owner layer 1 of the secret guard): the caller hands back the dry run's ``paths`` as
``confirmed_paths``. With none, :data:`CONFIRMATION_REQUIRED`; when the folder's list, built again at the push
by the same :func:`site_paths` and secret check, differs from it, :data:`LIST_CHANGED` with the ``added`` and
``removed`` paths in ``safe_details`` — both before the clone is touched. A confirmed file whose CONTENT
changed since the check still goes up (documented, not worked); the secret scan re-runs at the push.

The credential's Authorization rides as a per-call ``-c`` pair and is scrubbed from every error
(``realm_sync.git._git``).
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from .. import paths
from ..cli_format import object_envelope
from ..git_cmd import run_git
from ..realm_membership import CredentialSubject, RealmSyncCredential, ask_backend_permission
from ..realm_sync.families import is_secretish_path
from ..realm_sync.git import _git, _push_was_rejected, _redact_text, _scrub_config_values, run_sync_git
from ..realm_sync.models import RealmSyncError
from ..realm_sync.pull import file_contains_secret_assignment
from ..realm_sync.publish import PUBLISHER_TRAILER

__layer__ = "lanes"
__all__ = [
    "CONFIRMATION_REQUIRED",
    "DEFAULT_BRANCH",
    "IGNORE_FILE",
    "LIST_CHANGED",
    "NOT_CONNECTED",
    "SECRET_NAME_PATTERNS",
    "publish_folder",
    "site_paths",
]

#: The branch a Pages site is served from when the player picks "Deploy from a branch" (plan §3,
#: ``build_type: legacy``). The caller may name another.
DEFAULT_BRANCH = "gh-pages"
#: The refusal when no publishing repository is connected (no publishing credential was handed over).
NOT_CONNECTED = "publishing_not_connected"
#: The refusal of a push that does not hand back the confirmed list (the dry run's ``paths``).
CONFIRMATION_REQUIRED = "confirmation_required"
#: The refusal of a push whose folder no longer holds exactly the confirmed list; ``safe_details`` carry
#: ``added`` (in the folder now, not confirmed) and ``removed`` (confirmed, no longer in the folder).
LIST_CHANGED = "publishing_list_changed"
#: The empty file that tells Pages to serve the files as they are (no Jekyll build).
NOJEKYLL = ".nojekyll"
#: The folder's own ignore file: its patterns are left out of the publish (syntax: :func:`_read_ignore_file`).
#: A dotfile, so it never goes up itself.
IGNORE_FILE = ".publishignore"
#: File-name globs (case-insensitive, matched against each path part) that publishing refuses beside realm
#: sync's ``SECRET_PATH_MARKERS``: the ruled ``.env*``, ``id_rsa*``, ``*.pem``, ``*.key`` and the usual key and
#: credential files. ``.env*`` only bites through a path the default skip does not hide; it stays as ruled.
SECRET_NAME_PATTERNS = (
    ".env*",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "credentials.*",
    "*.credentials",
    "service-account*.json",
)
#: A private key's armour, whatever the file is called.
_PRIVATE_KEY_BLOCK = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
#: Files larger than this are not read for secrets (realm sync's own bound in ``file_contains_secret_assignment``).
_SCAN_LIMIT = 1_000_000
#: The robot every publishing commit is authored by; who published is the ``Eternia-Member`` trailer
#: (owner RULED 2026-11-14 on RT-REALM-SYNC-COMMITS-NAME-NOBODY: never an email or a real name).
#: ``core.autocrlf=false``: the bytes go up as they are on every OS.
_PUBLISHING_CONFIG = (
    "user.name=Hermes Realm Publishing",
    "user.email=realm-publishing@localhost",
    "core.autocrlf=false",
)


def publish_folder(
    realm_id: str,
    folder: str,
    *,
    credential: RealmSyncCredential | None,
    branch: str = DEFAULT_BRANCH,
    dry_run: bool = False,
    confirmed_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Publish ``folder`` to the realm's publishing repository's ``branch``. Returns the
    ``realm_publishing_push`` envelope; raises :class:`RealmSyncError` (``code``) on every refusal.
    ``confirmed_paths`` (the dry run's ``paths``, as the player confirmed them) is required unless
    ``dry_run``, and a dry run ignores it."""

    _require_this_device()
    source = _source_folder(folder)
    branch = _branch(branch)
    _require_connected(realm_id, credential)
    _require_permission(credential)
    files = site_paths(source)
    _refuse_secrets(source, files)
    if dry_run:
        return _envelope(realm_id, credential, branch, files=files, changed=False, commit=None, dry_run=True)
    _require_confirmed_list(files, confirmed_paths)
    repo = _publishing_clone(realm_id, credential)
    config = [*credential.git_extra_config(), *_PUBLISHING_CONFIG]
    tip = _fetch_tip(repo, branch, config)
    _replace_tree(repo, source, files)
    _git(repo, "add", "-A", "-f", "--", ".", extra_config=config)
    changed = tip is None or run_sync_git(["diff", "--cached", "--quiet", tip], repo=repo).returncode != 0
    if not changed:
        return _envelope(realm_id, credential, branch, files=files, changed=False, commit=tip, dry_run=False)
    member = credential.member_public_id
    trailer = ("-m", f"{PUBLISHER_TRAILER}: {member}") if member else ()
    _git(repo, "commit", "-q", "-m", f"Publish realm {realm_id}", *trailer, extra_config=config)
    _push_branch(repo, branch, config)
    commit = _git(repo, "rev-parse", "HEAD").strip()
    return _envelope(realm_id, credential, branch, files=files, changed=True, commit=commit, dry_run=False)


# ── the refusals ─────────────────────────────────────────────────────────────


def _require_this_device() -> None:
    """A device whose realm sync runs the pure-Python git (a phone: no git program) does not publish folders.

    Publishing clones, commits and pushes a folder from disk with the git program (``_git``), which a phone
    does not have, and realm sync's port leaves this verb out on purpose (plan
    phone-realm-sync-dulwich-2026-11-16 §7). Asked ONLY of the one backend selector, before any git or
    folder read — never a sniff of the git program or of the phone's stand-in — so the Launcher can word
    the refusal instead of an internal error (RT-PHONE-REALM-PUBLISHING-SAYS-NOT-ON-THIS-DEVICE)."""

    from ..realm_sync.git import SyncGitBackend, sync_git_backend

    if sync_git_backend() is SyncGitBackend.DULWICH:
        raise RealmSyncError(
            "publishing_not_on_this_device",
            "Publishing a realm's website is not available on this device; publish it from a computer.",
        )


def _source_folder(folder: str) -> Path:
    text = str(folder or "").strip()
    path = Path(text).expanduser() if text else None
    if path is None or not path.is_absolute():
        raise RealmSyncError("invalid_request", "folder must be an absolute path to the folder to publish.")
    if not path.is_dir():
        raise RealmSyncError("invalid_request", "There is no folder to publish at that path.")
    return path


def _branch(branch: str) -> str:
    name = str(branch or "").strip() or DEFAULT_BRANCH
    if run_git(["check-ref-format", "--branch", name]).returncode != 0:
        raise RealmSyncError("invalid_request", "branch is not a valid git branch name.")
    return name


def _require_connected(realm_id: str, credential: RealmSyncCredential | None) -> None:
    # MUTATION: drop this arm and test_nothing_connected_is_refused_plainly reddens.
    if credential is None:
        raise RealmSyncError(
            NOT_CONNECTED,
            "This realm has no publishing repository connected. Connect one in the realm's Publishing "
            "settings, then publish again.",
        )
    if credential.subject is not CredentialSubject.PUBLISHING:
        raise RealmSyncError(
            "sync_auth_failed",
            "This credential is not for a publishing repository.",
            safe_details={"credential_subject": credential.subject.value},
        )
    if credential.subject_id != realm_id:
        raise RealmSyncError("sync_auth_failed", "This publishing credential was issued for a different realm.")
    if credential.is_expired():
        raise RealmSyncError("sync_auth_failed", "The publishing credential has expired; request a fresh one.")


def _require_permission(credential: RealmSyncCredential) -> None:
    # MUTATION: skip this ask and test_a_member_the_backend_refuses_publishes_nothing reddens.
    decision = ask_backend_permission(credential, credential.subject_id, "publish")
    if not decision.allowed:
        raise RealmSyncError(
            decision.code or "membership_denied",
            decision.message or "You may not publish this realm.",
        )


def _require_confirmed_list(files: list[str], confirmed: list[str] | None) -> None:
    """Refuse a push unless the folder's list now is exactly the confirmed one."""

    # MUTATION: return instead of raising here and test_a_push_without_the_confirmed_list_pushes_nothing reddens.
    if confirmed is None:
        raise RealmSyncError(
            CONFIRMATION_REQUIRED,
            "Publishing needs the list of files the player confirmed (the check's paths).",
        )
    now, kept = set(files), set(confirmed)
    # MUTATION: return here and test_a_file_added_after_the_check_is_refused_by_name reddens.
    if now == kept:
        return
    added, removed = sorted(now - kept), sorted(kept - now)
    named = ", ".join([*(f"added {rel}" for rel in added[:5]), *(f"removed {rel}" for rel in removed[:5])])
    more = len(added) + len(removed) - min(len(added), 5) - min(len(removed), 5)
    raise RealmSyncError(
        LIST_CHANGED,
        f"The folder changed after you checked it ({named}{f' and {more} more' if more else ''}). "
        "Check the list again, then publish.",
        safe_details={"added": added, "removed": removed},
    )


def site_paths(source: Path) -> list[str]:
    """The folder's files that go up, as sorted relative POSIX paths: hidden entries and :data:`IGNORE_FILE`
    patterns left out. A symlink goes up as a link (git stores its target text), never followed."""

    ignore = _read_ignore_file(source)
    files: list[str] = []
    for top, dirs, names in os.walk(source):
        rel_top = PurePosixPath(Path(top).relative_to(source).as_posix())
        # MUTATION: keep hidden folders and test_hidden_files_and_folders_never_go_up reddens.
        kept = [d for d in dirs if not d.startswith(".") and not _ignored(rel_top / d, ignore, is_dir=True)]
        links = [d for d in kept if (Path(top) / d).is_symlink()]
        dirs[:] = sorted(d for d in kept if d not in links)
        for name in [*names, *links]:
            rel = rel_top / name
            # MUTATION: drop the ``startswith(".")`` arm and test_hidden_files_and_folders_never_go_up reddens.
            if name.startswith(".") or _ignored(rel, ignore, is_dir=False):
                continue
            files.append(rel.as_posix())
    if not files:
        raise RealmSyncError("invalid_request", "The folder to publish is empty.")
    return sorted(files)


def _read_ignore_file(source: Path) -> list[tuple[str, bool]]:
    """:data:`IGNORE_FILE`'s patterns as ``(glob, dirs_only)``. The syntax is a small subset of gitignore: one
    pattern a line; blank lines and lines starting with ``#`` are skipped; a trailing ``/`` matches folders only
    (and everything in them); a pattern holding a ``/`` elsewhere is anchored to the folder's top (a leading
    ``/`` is dropped), and one without matches a file or folder of that name at any depth; ``*``, ``?`` and
    ``[…]`` are shell globs (``fnmatch``, case-sensitive; ``*`` also crosses ``/`` in an anchored pattern).
    Negation (``!``) is not supported: a ``!`` line is an ordinary pattern."""

    try:
        text = (source / IGNORE_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    patterns: list[tuple[str, bool]] = []
    for line in text.splitlines():
        pattern = line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        dirs_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        if pattern:
            patterns.append((pattern, dirs_only))
    return patterns


def _ignored(rel: PurePosixPath, ignore: list[tuple[str, bool]], *, is_dir: bool) -> bool:
    # MUTATION: return False here and test_an_ignore_file_entry_is_left_out reddens.
    for pattern, dirs_only in ignore:
        if dirs_only and not is_dir:
            continue
        if "/" in pattern:
            if fnmatch.fnmatchcase(rel.as_posix(), pattern.lstrip("/")):
                return True
        elif fnmatch.fnmatchcase(rel.name, pattern):
            return True
    return False


def _refuse_secrets(source: Path, files: list[str]) -> None:
    """Refuse the whole publish, naming every file that still looks like a secret (``sync_secret_excluded``)."""

    # MUTATION: return here and test_a_secret_left_in_the_folder_refuses_the_publish_naming_it reddens.
    found = [rel for rel in files if _looks_secret(source, rel)]
    if found:
        shown = ", ".join(found[:10]) + (f" and {len(found) - 10} more" if len(found) > 10 else "")
        raise RealmSyncError(
            "sync_secret_excluded",
            f"These files look like secrets and a published site is public: {shown}. Move them out of the "
            f"folder or list them in {IGNORE_FILE}, then publish again.",
            safe_details={"paths": found},
        )


def _looks_secret(source: Path, rel: str) -> bool:
    if is_secretish_path(rel) or _secret_name(rel):
        return True
    path = source / rel
    if path.is_symlink():
        return False  # git carries the link's target text, not the file it points at
    return file_contains_secret_assignment(path) or _holds_private_key(path)


def _secret_name(rel: str) -> bool:
    # MUTATION: return False here and test_publishing_adds_its_own_secret_names reddens.
    return any(fnmatch.fnmatchcase(part.lower(), pattern) for part in PurePosixPath(rel).parts
               for pattern in SECRET_NAME_PATTERNS)


def _holds_private_key(path: Path) -> bool:
    try:
        if path.stat().st_size > _SCAN_LIMIT:
            return False
        return bool(_PRIVATE_KEY_BLOCK.search(path.read_bytes()))
    except OSError:
        return False


# ── the publishing clone ─────────────────────────────────────────────────────


def _publishing_clone(realm_id: str, credential: RealmSyncCredential) -> Path:
    """The realm's own publishing clone, its ``origin`` the credential's repository (the URL carries no
    secret; the Authorization is a per-call ``-c`` pair)."""

    repo = paths.realm_publishing_clone_dir(realm_id)
    if not (repo / ".git").is_dir():
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q")
    _git(repo, "remote", "remove", "origin", check=False)
    _git(repo, "remote", "add", "origin", credential.git_url)
    return repo


def _fetch_tip(repo: Path, branch: str, config: list[str]) -> str | None:
    """Put ``HEAD`` on ``branch`` at the remote's tip (fetched shallow), or on an unborn ``branch`` when the
    repository has none yet. Returns the tip, or ``None``."""

    ref = f"refs/heads/{branch}"
    listed = _git(repo, "ls-remote", "--heads", "origin", ref, extra_config=config).split()
    tip = listed[0] if listed else None
    _git(repo, "symbolic-ref", "HEAD", ref)
    if tip is None:
        _git(repo, "update-ref", "-d", ref, check=False)
        _git(repo, "read-tree", "--empty")
        return None
    _git(repo, "fetch", "-q", "--no-tags", "--depth=1", "origin", ref, extra_config=config)
    _git(repo, "update-ref", ref, tip)
    _git(repo, "read-tree", tip)
    return tip


def _replace_tree(repo: Path, source: Path, files: list[str]) -> None:
    """The working tree becomes exactly ``files`` (:func:`site_paths`, the list the dry run answered) plus
    ``.nojekyll`` — never a second walk of the folder."""

    for entry in repo.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for rel in files:
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target, follow_symlinks=False)
    (repo / NOJEKYLL).touch()


def _push_branch(repo: Path, branch: str, config: list[str]) -> None:
    proc = run_sync_git(["push", "-q", "origin", f"HEAD:refs/heads/{branch}"], repo=repo, config=config)
    if proc.returncode == 0:
        return
    stderr = _redact_text(_scrub_config_values(proc.stderr, config))
    if _push_was_rejected(proc.stderr):
        raise RealmSyncError(
            "sync_push_rejected", "Someone published this site at the same moment; publish again.",
            retryable=True, safe_details={"stderr": stderr},
        )
    code = "sync_auth_failed" if "authentication" in (proc.stderr or "").lower() else "sync_remote_unreachable"
    raise RealmSyncError(code, "The publishing repository refused the push.", retryable=True,
                         safe_details={"stderr": stderr})


def _envelope(realm_id: str, credential: RealmSyncCredential, branch: str, *, files: list[str], changed: bool,
              commit: str | None, dry_run: bool) -> dict[str, Any]:
    """``files`` is the count and ``paths`` the list (:func:`site_paths`) — ``.nojekyll``, which the verb adds,
    in neither."""

    return object_envelope("realm_publishing_push", {
        "realm_id": realm_id,
        "repository": credential.git_url,
        "branch": branch,
        "files": len(files),
        "paths": list(files),
        "changed": changed,
        "commit": commit,
        "dry_run": dry_run,
    })
