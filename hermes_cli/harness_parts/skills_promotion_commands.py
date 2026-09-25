"""Skill promotion, delete and restore: the verbs that move or archive a package.

Separate because these three write the shared skills root and the inbox, and
share the source-resolution and archive helpers nothing else reads.
"""

from __future__ import annotations

import re
from pathlib import Path

from hermes_cli.flag_binding import list_flag_or_empty
from agent_runtime.errors import NotFound
from agent_runtime.root_observability import attach_root_observability
from agent_runtime.realm_sync import skill_tombstone_rows
from agent_runtime.store import RealmStore
from hermes_cli.harness_support import (
    ERROR_EXIT_CODES,
    _error_envelope,
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

from .skills_commands import _rel_to_shared_skills

__layer__ = "lanes"
__all__ = [
    "_ARCHIVE_STAMP_SUFFIX_RE",
    "_PromotionSourceError",
    "_archive_content_hint",
    "_canonical_packages_covered",
    "_cmd_skills_delete",
    "_cmd_skills_promote",
    "_cmd_skills_restore",
    "_prune_inbox_packages",
    "_realm_publishes_skill",
    "_resolve_promotion_source",
    "_skill_delete_archive",
    "_skill_delete_coverage_warnings",
    "_skill_delete_envelope",
    "_skill_delete_realms",
    "_skill_delete_refusal",
    "_skill_delete_tombstones",
    "_skill_package_hashes",
]


def _resolve_promotion_source(args, skill: str):
    """Resolve exactly one promotion source.

    Returns ``(source_dir, source_meta, move_source)`` on success, or an
    ``(error_code, message, safe_details)`` triple wrapped in a
    :class:`_PromotionSourceError` on failure.
    """

    from agent_runtime.skill_promotion import list_inbox_packages, realm_inbox_dir

    from_realm = str(getattr(args, "from_realm", "") or "").strip() or None
    from_profile = str(getattr(args, "from_profile", "") or "").strip() or None
    from_path = str(getattr(args, "from_path", "") or "").strip() or None
    provided = [flag for flag, value in (("--from-realm", from_realm), ("--from-profile", from_profile), ("--from-path", from_path)) if value]
    slug_parts = skill.split("/")

    if len(provided) > 1:
        raise _PromotionSourceError("invalid_request", "Provide exactly one of --from-realm / --from-profile / --from-path.", {"skill": skill, "provided": provided})

    if not provided:
        # Implied source: exactly one realm inbox must hold the skill.
        matches = [row for row in list_inbox_packages() if row["skill"] == skill]
        if not matches:
            raise _PromotionSourceError("not_found", "Skill not held in any realm inbox — specify --from-realm / --from-profile / --from-path.", {"skill": skill})
        if len(matches) > 1:
            raise _PromotionSourceError("invalid_request", "Skill present in multiple realm inboxes — specify --from-realm <id>.", {"skill": skill, "candidates": sorted(row["realm"] for row in matches)})
        row = matches[0]
        return Path(row["source_dir"]), {"kind": "realm", "realm_id": row["realm"]}, False

    if from_realm:
        source_dir = realm_inbox_dir(from_realm).joinpath(*slug_parts)
        if not (source_dir / "SKILL.md").is_file():
            raise _PromotionSourceError("not_found", "Skill not present in that realm's inbox.", {"skill": skill, "realm": from_realm})
        # An inbox is a byte-faithful realm mirror — promotion never moves it.
        return source_dir, {"kind": "realm", "realm_id": from_realm}, False

    if from_profile:
        from hermes_cli.profiles import get_profile_dir, normalize_profile_name

        skills_root = get_profile_dir(normalize_profile_name(from_profile)) / "skills"
        candidate = skills_root.joinpath(*slug_parts)
        if (candidate / "SKILL.md").is_file():
            source_dir = candidate
        elif "/" not in skill:
            nested = [
                child / skill
                for child in sorted(skills_root.iterdir(), key=lambda p: p.name)
                if child.is_dir() and not child.name.startswith(".") and (child / skill / "SKILL.md").is_file()
            ] if skills_root.is_dir() else []
            if not nested:
                raise _PromotionSourceError("not_found", "Skill not found in that profile's skills directory.", {"skill": skill, "profile": from_profile})
            if len(nested) > 1:
                raise _PromotionSourceError("invalid_request", "Skill found under multiple categories in that profile — use <category>/<name>.", {"skill": skill, "profile": from_profile, "candidates": sorted(p.parent.name for p in nested)})
            source_dir = nested[0]
        else:
            raise _PromotionSourceError("not_found", "Skill not found in that profile's skills directory.", {"skill": skill, "profile": from_profile})
        # Promoting from a profile retires the duplicate (the collision guard).
        return source_dir, {"kind": "profile", "profile": from_profile}, True

    # from_path
    source_dir = Path(from_path).expanduser()
    if not (source_dir / "SKILL.md").is_file():
        raise _PromotionSourceError("not_found", "No SKILL.md at that path.", {"skill": skill})
    return source_dir, {"kind": "path", "path": str(source_dir)}, bool(getattr(args, "move_source", False))


class _PromotionSourceError(Exception):
    def __init__(self, code: str, message: str, safe_details: dict):
        super().__init__(message)
        self.code = code
        self.message = message
        self.safe_details = safe_details


def _cmd_skills_promote(args) -> int:
    """C4: hash-guarded promotion of a held / authored / profile-local package
    into the canonical shared root. Honors --dry-run (stage42 gate); never
    deletes (displaced content is archived)."""

    from agent_runtime.skill_promotion import classify_promotion, execute_promotion

    skill = str(getattr(args, "skill", "") or "").strip()
    dry_run = bool(getattr(args, "dry_run", False))
    adopt_divergent = bool(getattr(args, "adopt_divergent", False))

    try:
        source_dir, source_meta, move_source = _resolve_promotion_source(args, skill)
    except _PromotionSourceError as exc:
        _print_stage42(_error_envelope(exc.code, exc.message, safe_details=exc.safe_details), args=args, default_output="json")
        return ERROR_EXIT_CODES.get(exc.code, 1)

    plan = classify_promotion(skill, source_dir)

    # Installer-ownership policy, consulted BEFORE the divergence branch below.
    # The door enforces this too (``execute_promotion`` refuses without writing),
    # but reporting it here keeps the operator from being told "re-run with
    # --adopt-divergent" for a promotion that adopting could never make legal.
    # Same seam, one authority — the CLI adds only the exit code and hint.
    if plan.action in ("promote_new", "hold_divergent"):
        from agent_runtime.skill_publishability import promotion_refusal

        refusal = promotion_refusal(skill, source_dir)
        if refusal is not None:
            _print_stage42(
                _error_envelope(
                    "invalid_request",
                    refusal.message,
                    safe_details={
                        "skill": skill,
                        "reason_code": refusal.code,
                        "manifest_name": refusal.manifest_name,
                        "profile": refusal.profile,
                        "source_hash": plan.source_hash,
                        "canonical_hash": plan.canonical_hash,
                    },
                    hint=(
                        "The hermes installer owns this skill package. Promote a "
                        "package of your own under a distinct slug instead — see "
                        "`hermes harness skills publishable --json`."
                    ),
                ),
                args=args,
                default_output="json",
            )
            return ERROR_EXIT_CODES.get("invalid_request", 1)

    # A real (non-dry-run) divergent promotion without --adopt-divergent is a
    # hold: surface BOTH hashes in a typed payload and exit non-zero.
    if not dry_run and plan.action == "hold_divergent" and not adopt_divergent:
        _print_stage42(
            _error_envelope(
                "sync_conflict",
                "Canonical differs from source — re-run with --adopt-divergent to adopt (archives the previous copy).",
                safe_details={"skill": skill, "source_hash": plan.source_hash, "canonical_hash": plan.canonical_hash},
                hint="Re-run with --adopt-divergent to adopt the source over the divergent canonical (the previous copy is archived, never deleted).",
            ),
            args=args,
            default_output="json",
        )
        return ERROR_EXIT_CODES.get("sync_conflict", 1)

    result = execute_promotion(
        plan,
        source=source_meta,
        adopt_divergent=adopt_divergent,
        dry_run=dry_run,
        move_source=move_source,
    )

    envelope = _object_envelope(
        "skill_promotion",
        {
            "skill": skill,
            "source": source_meta,
            "classification": plan.action,
            "action": result.action,
            "source_hash": plan.source_hash,
            "canonical_hash": plan.canonical_hash,
            "archived_previous_to": _rel_to_shared_skills(result.archived_previous_to),
            "provenance_path": _rel_to_shared_skills(result.provenance_path),
            "reason": result.reason,
            # Machine-readable companion to ``reason`` when the guarded door
            # refuses on installer-ownership policy, so a UI branches on a code
            # instead of pattern-matching prose (None otherwise).
            "reason_code": result.reason_code,
            "dry_run": dry_run,
        },
    )
    _print_stage42(envelope, args=args, default_output="json")
    return 2 if result.action == "refused" else 0


# ── skills delete / restore (canon: docs/agent-runtime-harness/01-system-architecture.md §Skills) ──


def _canonical_packages_covered(slug: str) -> list[tuple[str, Path]]:
    """Every canonical package a tombstone on ``slug`` would cover.

    ONE match rule (``store.skill_tombstone_matches``), asked in the direction
    this verb has to ask it: holding a CANDIDATE entry slug, before any ledger
    exists to hand ``skill_tombstoned``. Plural by construction — a bare-name
    entry covers a categorized ``<cat>/<child>`` package of the same child name,
    so ``foo`` can name both a top-level ``foo`` and a ``bar/foo``.
    """

    from agent_runtime.skill_promotion import iter_skill_packages
    from agent_runtime.store import skill_tombstone_matches
    from agent_runtime.profile_home import get_shared_skills_dir

    return [
        (pkg_slug, pkg_dir)
        for pkg_slug, pkg_dir in iter_skill_packages(get_shared_skills_dir())
        if skill_tombstone_matches(slug, pkg_slug)
    ]


def _realm_publishes_skill(realm, slug: str, covered_slugs: list[str]) -> bool:
    """Does this realm CURRENTLY publish ``slug``? (R-E's default target set.)

    Answered the way ``_skill_artifacts`` answers it, because that is what
    "currently publishes" means on this machine:

    - mode ``all`` publishes whatever the canonical root holds, so the realm
      publishes the slug exactly when a local package is covered by it;
    - mode ``selected`` publishes what the selection NAMES, which is a standing
      statement about the name and holds even with no local copy.

    A realm whose ledger already carries the slug is a target too: a repeat
    delete refreshes ``deleted_at`` rather than quietly skipping a realm the
    operator would then believe was left alone.

    With no local package the selection entry is only a NAME, and a name cannot
    say whether ``foo`` and ``cat/foo`` are the same package — so that arm
    accepts the match in EITHER direction rather than silently missing a realm.
    Where packages exist, the packages decide.
    """

    from agent_runtime.store import skill_tombstone_matches, skill_tombstoned

    if skill_tombstoned(realm, slug) is not None:
        return True
    if realm.skill_publish_mode == "selected":
        selection = realm.skill_selection or []
        if covered_slugs:
            # The selection rule and the tombstone rule are ONE rule by design
            # (see store.skill_tombstone_matches): a slug must not be able to be
            # simultaneously "selected" and "not the thing that was deleted".
            return any(
                skill_tombstone_matches(entry, pkg_slug)
                for entry in selection
                for pkg_slug in covered_slugs
            )
        return any(
            skill_tombstone_matches(slug, entry) or skill_tombstone_matches(entry, slug)
            for entry in selection
        )
    return bool(covered_slugs)


def _prune_inbox_packages(realm_id: str, slug: str) -> list[str]:
    """Drop this realm's inbox-mirror copies that a tombstone on ``slug`` covers.

    UNLINKED, not archived — deliberately, and it is not a breach of the skills
    lane's never-delete invariant. That invariant protects authored content; the
    inbox is a byte-faithful CACHE of what the realm publishes, rebuilt from the
    subtree on every pull, and ``_mirror_realm_skill_inbox`` already unlinks a
    package the realm stopped publishing. The canonical copy — the authored one
    — is what the delete archives.

    Without this step the operator would delete a skill and still see it in
    ``skills inbox`` as a promotable package until the next pull.
    """

    import shutil

    from agent_runtime.skill_promotion import iter_skill_packages, realm_inbox_dir
    from agent_runtime.store import skill_tombstone_matches

    inbox = realm_inbox_dir(realm_id)
    pruned: list[str] = []
    for pkg_slug, pkg_dir in list(iter_skill_packages(inbox)):
        if not skill_tombstone_matches(slug, pkg_slug):
            continue
        shutil.rmtree(pkg_dir, ignore_errors=True)
        parent = pkg_dir.parent
        # A category dir left empty by the prune is removed too, so the mirror
        # does not accumulate hollow shells the next `iter_skill_packages` walk
        # has to step over.
        if parent != inbox and parent.is_dir() and not any(parent.iterdir()):
            try:
                parent.rmdir()
            except OSError:
                pass
        pruned.append(pkg_slug)
    return sorted(pruned)


_ARCHIVE_STAMP_SUFFIX_RE = re.compile(r"-\d+$")


def _archive_content_hint(slug: str) -> dict:
    """Where the BYTES of a deleted skill are, and the command that re-admits them.

    ``skills restore`` lifts a ledger entry and nothing else (R-C) — content is
    the promotion lane's job. This hint is what keeps that split from being a
    dead end: it names the newest ``.archive/<UTC ts>/<flat>`` copy (archive
    stamp dirs sort chronologically because they are UTC timestamps) and the
    exact promote command for it, paths rendered relative to the hermes root the
    way the plan writes them.

    ``candidates`` is honest about repeats: deleting and re-promoting the same
    slug leaves several archived copies, and the newest is a choice, not a fact.
    """

    from hermes_constants import get_default_hermes_root
    from agent_runtime.profile_home import get_shared_skills_dir

    shared = get_shared_skills_dir()
    flat = slug.replace("/", "__")
    archive_root = shared / ".archive"
    matches: list[Path] = []
    if archive_root.is_dir():
        for stamp in sorted(p for p in archive_root.iterdir() if p.is_dir()):
            for candidate in sorted(p for p in stamp.iterdir() if p.is_dir()):
                name = candidate.name
                # ``_archive_dir``'s collision breaker appends ``-<n>``; a real
                # skill literally named ``<flat>-1`` would also match here, which
                # is why ``candidates`` is reported rather than one path claimed
                # as the only answer.
                if name != flat and _ARCHIVE_STAMP_SUFFIX_RE.sub("", name) != flat:
                    continue
                if (candidate / "SKILL.md").is_file():
                    matches.append(candidate)
    newest = matches[-1] if matches else None
    rel = None
    if newest is not None:
        # Rendered relative to the hermes ROOT (the plan's own spelling,
        # ``shared/skills/.archive/<ts>/<slug>``) and never absolute — the error
        # contract forbids leaking the runtime root. A HERMES_SHARED_SKILLS
        # override moves the shared dir out from under the root, and then the
        # shared-root-relative path is the only honest answer available.
        try:
            rel = newest.relative_to(get_default_hermes_root()).as_posix()
        except ValueError:
            rel = newest.relative_to(shared).as_posix()
    return {
        "archived": newest is not None,
        "path": rel,
        "candidates": len(matches),
        "promote_command": (
            f"hermes harness skills promote {slug} --from-path {rel}" if rel else None
        ),
    }


def _cmd_skills_delete(args) -> int:
    """Delete a shared skill realm-wide: archive the local canonical package and
    record the tombstone git absence cannot carry (plan §4).

    The bytes really are deleted everywhere — publish is a full-subtree replace,
    so the propagating push removes the file and every member's pull removes it
    from their clone. What git cannot reach is the ADOPTED copy in each member's
    canonical skills root, which is not a git file and which rides that member's
    next publish straight back into the realm. The ledger is that instruction.

    Five steps, in order: refuse (before anything is written), select the
    realms, tombstone them, archive the local packages (and prune each realm's
    inbox), report.
    """

    slug = str(getattr(args, "skill", "") or "").strip()
    dry_run = bool(getattr(args, "dry_run", False))
    refused = _skill_delete_refusal(slug, args)
    if refused is not None:
        return refused

    store = RealmStore()
    covered = _canonical_packages_covered(slug)
    covered_slugs = [pkg_slug for pkg_slug, _pkg_dir in covered]
    realms, refused = _skill_delete_realms(store, args, slug, covered_slugs)
    if refused is not None:
        return refused

    hashes = _skill_package_hashes(covered)
    deleted_hash = hashes.get(covered_slugs[0]) if covered_slugs else None
    realm_rows, refused = _skill_delete_tombstones(store, realms, slug, deleted_hash, dry_run, args)
    if refused is not None:
        return refused

    warnings: list[dict] = []
    archived_rows = _skill_delete_archive(covered, hashes, dry_run, warnings)
    if not dry_run:
        for row, realm in zip(realm_rows, realms):
            row["inbox_pruned"] = _prune_inbox_packages(realm.id, slug)
    warnings.extend(_skill_delete_coverage_warnings(slug, covered, realm_rows))
    _print_stage42(
        _skill_delete_envelope(slug, realm_rows, archived_rows, deleted_hash, dry_run, warnings),
        args=args,
        default_output="json",
    )
    return 0


def _skill_delete_refusal(slug: str, args) -> int | None:
    """The exit code of a refusal printed before anything is written, or None."""
    from agent_runtime.skill_promotion import validate_skill_slug
    from agent_runtime.profile_home import CANONICAL_SHARED_SKILL_IDS

    # Refuse BEFORE anything is written, reading the SAME two authorities the
    # store chokepoint reads (``validate_skill_slug`` and the constant) rather
    # than re-spelling either. This is not the fence — ``tombstone_skill``
    # refuses on its own — it is the fence answering before N realms have been
    # written and before the archive step has moved bytes.
    reason = validate_skill_slug(slug)
    if reason is not None:
        _print_stage42(
            _error_envelope(
                "skill_slug_invalid",
                f"{slug!r} is not a valid skill slug: {reason}",
                safe_details={"skill": slug},
            ),
            args=args,
            default_output="json",
        )
        return ERROR_EXIT_CODES["skill_slug_invalid"]
    if slug in CANONICAL_SHARED_SKILL_IDS:
        _print_stage42(
            _error_envelope(
                "skill_installer_owned",
                (
                    f"{slug!r} is a hermes-installed harness skill: every realm pull "
                    "reinstalls it from repo source, so a realm tombstone can never "
                    "hold. Delete it from agent_runtime.profile_home.CANONICAL_SHARED_SKILL_IDS "
                    "and docs/agent-runtime-harness/harness-skills/ instead."
                ),
                safe_details={"skill": slug},
            ),
            args=args,
            default_output="json",
        )
        return ERROR_EXIT_CODES["skill_installer_owned"]
    return None


def _skill_delete_realms(store, args, slug: str, covered_slugs: list[str]) -> tuple[list, int | None]:
    """The realms this delete tombstones: the ones ``--realm`` names, else every
    realm that publishes the slug. A named realm that does not exist refuses."""
    requested: list[str] = []
    for value in list_flag_or_empty(args, "realms"):
        token = str(value or "").strip()
        if token and token not in requested:
            requested.append(token)
    if not requested:
        return [
            realm
            for realm in store.list_all()
            if _realm_publishes_skill(realm, slug, covered_slugs)
        ], None
    # An explicitly named realm is honored even when it does not currently
    # publish the slug (and even when archived): the operator named it, and a
    # tombstone records INTENT.
    realms = []
    for realm_id in requested:
        try:
            realms.append(store.get(realm_id))
        except NotFound as exc:
            return [], emit_harness_error(exc, args=args, code="not_found")
    return realms, None


def _skill_package_hashes(covered) -> dict[str, str | None]:
    from agent_runtime.skill_resolution import skill_package_content_hash

    hashes: dict[str, str | None] = {}
    for pkg_slug, pkg_dir in covered:
        try:
            hashes[pkg_slug] = skill_package_content_hash(pkg_dir, pkg_dir / "SKILL.md")
        except Exception:  # noqa: BLE001 — evidence, never a reason to refuse
            hashes[pkg_slug] = None
    return hashes


def _skill_delete_tombstones(store, realms, slug: str, deleted_hash, dry_run: bool, args) -> tuple[list[dict], int | None]:
    """One tombstone per realm, and its receipt row; a store refusal stops the verb."""
    from agent_runtime.errors import SkillTombstoneRefused
    from agent_runtime.store import active_skill_tombstones

    realm_rows: list[dict] = []
    for realm in realms:
        before = set(realm.skill_selection or [])
        # ``refreshed`` asks for the EXACT entry, because that is the entry
        # ``tombstone_skill`` dedupes against (a bare-name entry that merely
        # COVERS this slug is a different record and is not replaced). It asks
        # the ACTIVE ledger: since RD-11 a restored entry stays on the register,
        # and re-deleting a slug someone lifted is a fresh delete, not a refresh
        # of a block that was standing.
        refreshed = any(entry.slug == slug for entry in active_skill_tombstones(realm))
        try:
            updated = store.tombstone_skill(
                realm.id, slug, deleted_hash=deleted_hash, dry_run=dry_run
            )
        except SkillTombstoneRefused as exc:
            _print_stage42(
                _error_envelope(
                    exc.code,
                    str(exc),
                    safe_details={**exc.safe_details, "realm_id": realm.id},
                ),
                args=args,
                default_output="json",
            )
            return realm_rows, ERROR_EXIT_CODES.get(exc.code, 1)
        realm_rows.append(
            {
                "realm_id": realm.id,
                "tombstoned": True,
                # A LIST, not a bool: the plan's row shape left the type open and
                # a bool cannot say WHICH selection entry a bare-name tombstone
                # took (R-F prunes through the same match rule).
                "selection_pruned": sorted(before - set(updated.skill_selection or [])),
                "refreshed": refreshed,
                "inbox_pruned": [],
            }
        )
    return realm_rows, None


def _skill_delete_archive(covered, hashes: dict, dry_run: bool, warnings: list[dict]) -> list[dict]:
    """Archive each covered local package; a failure is a warning, never silent."""
    from agent_runtime.skill_promotion import _archive_package

    archived_rows: list[dict] = []
    for pkg_slug, pkg_dir in covered:
        if dry_run:
            archived_rows.append(
                {"slug": pkg_slug, "archived_to": None, "deleted_hash": hashes.get(pkg_slug)}
            )
            continue
        try:
            dest = _archive_package(pkg_dir, pkg_slug)
        except Exception as exc:  # noqa: BLE001 — accounted, never silent
            warnings.append(
                {"code": "skill_archive_failed", "skill": pkg_slug, "message": str(exc)}
            )
            continue
        archived_rows.append(
            {
                "slug": pkg_slug,
                "archived_to": _rel_to_shared_skills(dest),
                "deleted_hash": hashes.get(pkg_slug),
            }
        )
    return archived_rows


def _skill_delete_coverage_warnings(slug: str, covered, realm_rows: list[dict]) -> list[dict]:
    if not covered and not realm_rows:
        return [
            {
                "code": "skill_unknown",
                "skill": slug,
                "message": (
                    "No canonical package here and no non-archived realm currently "
                    "publishing it — nothing was written. A tombstone records INTENT "
                    "and is valid without a local copy: name the realm explicitly "
                    "with --realm to record one anyway."
                ),
            }
        ]
    if not covered:
        return [
            {
                "code": "skill_no_local_package",
                "skill": slug,
                "message": (
                    "Tombstone recorded, nothing archived: no canonical package for "
                    "this slug exists on this machine. The intent still travels and "
                    "still blocks members who do hold one."
                ),
            }
        ]
    return []


def _skill_delete_envelope(slug: str, realm_rows, archived_rows, deleted_hash, dry_run: bool, warnings) -> dict:
    if len(realm_rows) == 1:
        next_step = (
            f"hermes harness realm sync publish {realm_rows[0]['realm_id']} to propagate"
        )
    else:
        # Zero or many targets: the placeholder is the honest rendering — the
        # publish has to be run once per realm the receipt lists.
        next_step = "hermes harness realm sync publish <realm> to propagate"

    payload = {
        "skill": slug,
        "realms": realm_rows,
        # ``archived`` is the truth and the two scalars below are the §4
        # single-package convenience: the match rule is one-to-many by
        # construction, so a lone ``archived_to`` cannot describe a bare-name
        # delete that covered a top-level AND a categorized package.
        "archived": archived_rows,
        "archived_to": archived_rows[0]["archived_to"] if archived_rows else None,
        "deleted_hash": deleted_hash,
        "next": next_step,
    }
    if dry_run:
        payload["dry_run"] = True
    # This lane is the root-observability gate's own defect class, exactly: a
    # delete resolved against the WRONG shared root finds no package, resolves
    # no publishing realm, and reports a well-formed ``skill_unknown`` — the
    # operator reads "already gone" from a verb that never looked in the right
    # place. The envelope has to say which root answered.
    return attach_root_observability(
        _object_envelope("skill_delete", payload, warnings=warnings or None)
    )


def _cmd_skills_restore(args) -> int:
    """Lift ONE realm's skill tombstone. Un-tombstone only (R-C).

    The store returns the realm, not a ``restored`` flag, so the answer is taken
    BEFORE the write: an ACTIVE entry with exactly this slug is what
    ``restore_skill`` lifts, and an idempotent no-op — an absent entry, or one
    already lifted — must report ``restored: false`` rather than claim a change
    it did not make.
    """

    from agent_runtime.store import active_skill_tombstones, skill_tombstoned

    slug = str(getattr(args, "skill", "") or "").strip()
    realm_id = str(getattr(args, "realm", "") or "").strip()
    if not slug or not realm_id:
        return emit_harness_error(
            ValueError("a skill slug and --realm <id> are both required"),
            args=args,
            code="invalid_request",
        )

    store = RealmStore()
    try:
        realm = store.get(realm_id)
    except NotFound as exc:
        return emit_harness_error(exc, args=args, code="not_found")

    had_entry = any(entry.slug == slug for entry in active_skill_tombstones(realm))
    updated = store.restore_skill(realm_id, slug)

    warnings: list[dict] = []
    blocking = skill_tombstoned(updated, slug)
    if blocking is not None:
        # A categorized package can be blocked by a BARE-name entry; lifting
        # ``cat/child`` leaves ``child`` standing, and a receipt that said
        # "restored" without saying so would be a lie of omission.
        warnings.append(
            {
                "code": "skill_still_tombstoned",
                "skill": slug,
                "blocking_slug": blocking.slug,
                "message": (
                    f"Ledger entry {blocking.slug!r} still covers this slug — restore "
                    "that entry to un-block it."
                ),
            }
        )
    if not had_entry:
        warnings.append(
            {
                "code": "skill_not_tombstoned",
                "skill": slug,
                "message": "No ledger entry with this exact slug in that realm; nothing was written.",
            }
        )

    payload = {
        "skill": slug,
        "realm_id": updated.id,
        "restored": had_entry,
        "tombstones": skill_tombstone_rows(updated),
        # R-C's other half: the entry is lifted, the BYTES are the promotion
        # lane's job, and this names the copy the delete archived so the
        # two-step is a command to run rather than a data-recovery hunt.
        "content_hint": _archive_content_hint(slug),
    }
    # Same reason as the delete: ``content_hint.archived: false`` is a
    # well-formed empty answer, and a wrong shared root produces it just as
    # readily as a genuinely-unarchived slug does.
    envelope = attach_root_observability(
        _object_envelope("skill_restore", payload, warnings=warnings or None)
    )
    _print_stage42(envelope, args=args, default_output="json")
    return 0
