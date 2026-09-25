"""The skill lane of a pull: mirror the realm's packages into the inbox, admit each one.

The inbox is resolver-invisible; each package is classified three-way and admitted
only through the one guarded promotion door.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..models import Realm
from ..store import skill_tombstoned
from .models import _canonicalize_text_bytes

logger = logging.getLogger(__name__)

__layer__ = "lanes"
__all__ = [
    "SkillSyncSummary",
    "_held_skill_packages_for_realm",
    "_mirror_realm_skill_inbox",
    "_prune_empty_dirs",
    "_subtree_package_slug",
    "apply_skill_inbox_pull",
]


@dataclass(frozen=True, slots=True)
class SkillSyncSummary:
    """Outcome of :func:`apply_skill_inbox_pull` — the per-package reconcile
    verdicts for one realm pull. ``adopted`` were promoted new into the canonical
    root, ``converged`` already matched canonical (no write), ``updated`` were
    realm-side changes fast-forwarded over an untouched local copy (the previous
    canonical archived), ``kept_local`` are MY unpublished edits against an unmoved
    realm copy (no write — they surface as ``store_drift.skills``), ``held`` diverge
    on BOTH sides and were quarantined without touching canonical (an operator
    resolves them with ``hermes harness realm sync resolve <realm> --key
    skill::<slug> --take local|remote``), ``removed`` were pruned
    from the inbox because the realm no longer publishes them, and ``refused`` are
    packages the guarded door would not admit — an invalid/hostile/reserved slug,
    a canonical slot occupied by a non-skill-package (a bare-slug landing on an
    existing category dir, or a categorized child whose parent is a bare skill),
    or a per-package error — isolated so ONE bad package can never abort the pull.
    Refused packages are deliberately kept OUT of ``skills_drift`` (which stays the
    held-divergent set the operator resolves); they are surfaced only here.
    ``tombstoned`` are packages a still-stale publisher put in the subtree that
    the realm's skill-delete ledger blocks: they are dropped from the mirror
    exactly like a ``removed`` package, so the promotion loop never sees them and
    a tombstoned slug can never auto-adopt. All lists are sorted, de-duplicated
    skill slugs (bare or ``<category>/<name>``)."""

    adopted: list[str]
    converged: list[str]
    held: list[str]
    removed: list[str]
    refused: list[str]
    tombstoned: list[str] = ()  # type: ignore[assignment]
    #: ``updated`` and ``kept_local`` are the THREE-WAY model's two new verdicts
    #: (2026-09-12). ``updated`` is a realm-side change adopted over an UNTOUCHED
    #: local copy — the fast-forward every sibling family already had, and which
    #: this family used to report as a hold for every member who merely owned the
    #: skill. ``kept_local`` is the mirror image: MY edit against an unmoved realm
    #: copy, so nothing is written and the package shows up as unpublished drift
    #: (``store_drift.skills``) with Publish and Revert as its exits.
    updated: list[str] = ()  # type: ignore[assignment]
    kept_local: list[str] = ()  # type: ignore[assignment]

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "adopted": list(self.adopted),
            "converged": list(self.converged),
            "held": list(self.held),
            "removed": list(self.removed),
            "refused": list(self.refused),
            # Additive key — the launcher's realm-sync sheet is absent-tolerant
            # (the ``store_drift`` precedent), so an older reader ignores it.
            "tombstoned": list(self.tombstoned),
            # Additive for the same reason, and the launcher reads them as
            # nullable (``RealmSkillSyncOutcome.updated`` / ``keptLocal``), so an
            # older hermes is "this build has no three-way skill lane" rather
            # than "nothing was updated".
            "updated": list(self.updated),
            "kept_local": list(self.kept_local),
        }


def apply_skill_inbox_pull(realm: Realm, subtree: Path) -> SkillSyncSummary:
    """Mirror the pulled ``subtree/skills/**`` into the realm's resolver-invisible
    inbox, then reconcile each package through the one guarded promotion door.

    Mirrors the board/office pull-applier precedent (``apply_board_pull`` /
    ``apply_office_pull``): the generic overwrite loop no longer touches
    ``skills/…`` (``_destination_for_sync_path`` returns ``None``), so this owns
    the whole skill lane. The inbox is a byte-faithful, LF-canonical copy of that
    realm's current skill packages that the resolver never sees
    (``EXCLUDED_SKILL_DIRS`` — C1). Each package is then classified THREE-WAY —
    local canonical vs the never-synced baseline sidecar vs the realm's copy —
    through the shared :func:`sync_merge.classify_three_way_pull`, exactly as
    every sibling family does, via the ONE classifier
    :func:`agent_runtime.skill_sync.classify_inbox_package`:

    - no canonical copy → auto-adopted, provenance recorded
      (``source={"kind": "realm", "realm_id": realm.id}``); the inbox mirror is
      **never** moved (``move_source=False``). Bucket ``adopted``.
    - local == remote → ``converged``; canonical untouched.
    - local == baseline, remote moved → the realm's copy is installed over mine
      through the same guarded door with ``adopt_divergent=True`` (my previous
      canonical ARCHIVED, never deleted). Bucket ``updated``. **This is the case
      the two-way compare got wrong**: it held every member who merely owned the
      skill, forever, over a change nobody disagreed with.
    - local moved, remote == baseline → ``kept_local``: nothing is written, and
      the package surfaces as unpublished drift (``store_drift.skills``) whose
      exits are Publish and Revert.
    - both moved → ``held``; canonical untouched, surfaced as ``skills_drift``,
      which therefore now means CONFLICTS ONLY.

    The baseline advances to the remote hash for ``converged`` / ``adopted`` /
    ``updated`` — never for ``kept_local`` (that would erase the operator's
    unpublished edit from the accounting) and never for ``held`` (nothing has been
    seen-and-accepted) — and a ``removed`` package's entry is dropped with it.

    A package the realm's skill-delete ledger blocks never reaches that
    classification at all: the mirror drops it (``tombstoned``), so a stale
    publisher's surviving copy cannot walk back in through the auto-adopt door.
    ``realm`` must therefore be the PULLED record — ``pull_realm_sync`` re-reads
    it after the artifact overwrite loop.

    Never called on a dry-run pull (``pull_realm_sync`` returns before this),
    so the mirror — itself a mutation — is skipped when ``dry_run=True``.
    """

    from ..skill_promotion import (
        _iter_packages,
        classify_promotion,
        execute_promotion,
        realm_inbox_dir,
    )
    from ..skill_sync import (
        BASELINE_ADVANCING_BUCKETS,
        BUCKET_ADOPTED,
        BUCKET_CONVERGED,
        BUCKET_KEPT_LOCAL,
        BUCKET_UPDATED,
        classify_inbox_package,
        read_skill_baseline,
        record_converged_skill_baselines,
        skill_baseline_key,
        write_skill_baseline,
    )

    inbox = realm_inbox_dir(realm.id)
    # Installs that predate the sidecar (2026-09-12): where the canonical copy and
    # the PRE-mirror inbox — the realm as of my last sync — already agree, that
    # agreement is the baseline, recorded before the mirror rewrites the inbox.
    # Only agreement is recorded; see ``seed_converged_skill_baselines`` for why
    # the broad "inbox stands in for the baseline" rule was wrong.
    record_converged_skill_baselines(realm.id, inbox)
    removed, reserved_refused, tombstoned = _mirror_realm_skill_inbox(
        subtree / "skills",
        inbox,
        tombstoned=lambda slug: skill_tombstoned(realm, slug) is not None,
    )

    adopted: list[str] = []
    converged: list[str] = []
    updated: list[str] = []
    kept_local: list[str] = []
    held: list[str] = []
    # Packages the mirror skipped (a reserved device-name component would crash a
    # Windows write) start the refused set; each is already NOT on disk.
    refused: list[str] = list(reserved_refused)
    # ONE baseline read for the whole loop, ONE write at the end. Read per
    # package it would be the same bytes N times; written per package, a raise
    # mid-loop would leave a sidecar agreeing with neither the inbox nor the
    # canonical root.
    baseline = read_skill_baseline(realm.id)
    baseline_dirty = False
    # A package the realm stopped publishing takes its baseline entry with it:
    # the entry means "the realm's copy was this when I last saw it", and there is
    # no realm copy any more. Left behind, it reports a ``removed`` drift row
    # whose revert would reinstall a package the realm dropped.
    for gone in removed:
        if baseline.pop(skill_baseline_key(gone), None) is not None:
            baseline_dirty = True
    # Iterate the mirrored inbox package-by-package with per-package isolation:
    # a package that refuses OR raises (a malformed source, a TOCTOU-occupied
    # canonical slot, an unexpected I/O error) must never abort the whole pull —
    # it is recorded as ``refused`` and reconciliation continues (F1c).
    from ..sync_admission import refuse_package

    for slug, source_dir in _iter_packages(inbox):
        try:
            # Admission scan (defect (b), 2026-07-25): the generic pull loop's
            # ``_assert_no_secret_artifacts`` only covers artifacts it MAPS, and
            # ``skills/…`` maps to None — so a pulled package was never scanned
            # on the way in. Per-package isolation: one hostile package is
            # refused, the rest of the pull continues. Portability is
            # deliberately NOT scanned here — a skill's documentation
            # legitimately names absolute paths (see ``sync_admission``).
            refusal = refuse_package(slug, source_dir)
            if refusal is not None:
                logger.warning("skill package refused at the realm door: %s (%s)", slug, refusal.code)
                refused.append(slug)
                continue
            # The promotion door's STRUCTURAL verdict first — it owns the
            # refusals the three-way model has no opinion about (an invalid slug,
            # a canonical slot occupied by a non-package, a categorized child
            # under a bare skill) — then the DIRECTION, from the shared
            # classifier. Two different questions: the write door dispatches on
            # the first, the operator reads the second.
            plan = classify_promotion(slug, source_dir)
            if plan.action == "refuse_invalid":
                refused.append(slug)
                continue
            verdict = classify_inbox_package(
                realm.id, slug, source_dir, plan=plan, baseline=baseline
            )
            bucket = verdict.bucket
            if bucket == BUCKET_ADOPTED:
                result = execute_promotion(
                    plan,
                    source={"kind": "realm", "realm_id": realm.id},
                    move_source=False,
                )
            elif bucket == BUCKET_UPDATED:
                # The fast-forward. ``adopt_divergent=True`` is what makes the
                # door archive my previous canonical before installing the
                # realm's, so the copy being replaced is recoverable from
                # ``.archive/<ts>/`` exactly as an explicit adopt's is.
                result = execute_promotion(
                    plan,
                    source={"kind": "realm", "realm_id": realm.id},
                    adopt_divergent=True,
                    move_source=False,
                )
            else:
                result = None
            if result is not None:
                if result.action == "promoted":
                    (adopted if bucket == BUCKET_ADOPTED else updated).append(slug)
                elif result.action == "held":
                    held.append(slug)
                    bucket = None  # never advance a baseline over a write that did not land
                else:  # 'refused' / anything non-terminal — never became canonical
                    refused.append(slug)
                    bucket = None
            elif bucket == BUCKET_CONVERGED:
                converged.append(slug)
            elif bucket == BUCKET_KEPT_LOCAL:
                kept_local.append(slug)
            else:  # held, or a defensively-mapped unreachable reason
                held.append(slug)
            if bucket in BASELINE_ADVANCING_BUCKETS and verdict.remote_hash is not None:
                key = skill_baseline_key(slug)
                if baseline.get(key) != verdict.remote_hash:
                    baseline[key] = verdict.remote_hash
                    baseline_dirty = True
        except Exception:  # noqa: BLE001 — one bad package must not abort the pull
            logger.exception(
                "skill inbox reconcile raised for %r (realm %s); refusing package",
                slug,
                realm.id,
            )
            refused.append(slug)
    if baseline_dirty:
        try:
            write_skill_baseline(realm.id, baseline)
        except Exception:  # noqa: BLE001 — a baseline is a receipt; it never fails a pull
            logger.exception("skill baseline write failed for realm %s", realm.id)
    return SkillSyncSummary(
        adopted=sorted(set(adopted)),
        converged=sorted(set(converged)),
        held=sorted(set(held)),
        removed=sorted(set(removed)),
        refused=sorted(set(refused)),
        tombstoned=sorted(set(tombstoned)),
        updated=sorted(set(updated)),
        kept_local=sorted(set(kept_local)),
    )


def _subtree_package_slug(source_skills: Path, rel_parts: tuple[str, ...]) -> str | None:
    """Which published package does ``rel_parts`` belong to?

    Answers with the SAME package-shape rules the promotion door and the
    publisher use (``iter_skill_packages`` / ``_iter_publishable_skill_packages``):
    a top-level dir with a ``SKILL.md`` is a bare package; otherwise its
    immediate children are ``<category>/<child>``. ``None`` for a loose file at
    the root of ``skills/``, which belongs to no package.

    Needed because the mirror works on FILES while the tombstone ledger names
    packages: dropping by top-level component alone would take a categorized
    package's innocent siblings with it.
    """

    if not rel_parts:
        return None
    top = rel_parts[0]
    if (source_skills / top / "SKILL.md").is_file():
        return top
    if len(rel_parts) >= 2:
        return f"{top}/{rel_parts[1]}"
    return None


def _mirror_realm_skill_inbox(
    source_skills: Path,
    inbox: Path,
    *,
    tombstoned=None,
) -> tuple[list[str], list[str], list[str]]:
    """Mirror ``source_skills`` (the pulled ``subtree/skills``) into ``inbox`` as
    an LF-canonical, resolver-invisible copy.

    Returns ``(removed, reserved_refused, tombstoned)``: ``removed`` are the
    top-level packages pruned (present in the inbox, gone from the subtree);
    ``reserved_refused`` are
    the top-level packages skipped WITHOUT any write because a relative path
    component maps to a Windows reserved device name (``con`` / ``nul`` /
    ``com1`` … — a realm publishing such a package would otherwise crash the
    mirror on Windows, a pull DoS). Reserved packages are skipped on every
    platform for deterministic behaviour (a reserved slug can never be promoted
    anyway — ``validate_skill_slug`` refuses it) and reported so the caller can
    record them as ``refused``.

    ``tombstoned`` are the package slugs the realm's skill-delete ledger blocks
    (``tombstoned`` predicate, the ONE match rule in ``store.skill_tombstoned``).
    They are excluded from the desired set, so an already-mirrored copy is
    unlinked exactly like a ``removed`` one and the promotion loop never sees
    them. Filtering is per PACKAGE, not per top-level dir, so a tombstoned
    ``<category>/<child>`` never takes its siblings with it.

    Text is LF-normalized at this write chokepoint (matching the publisher's
    ``_canonicalize_text_bytes``) so a package converges against an LF canonical
    regardless of the incoming EOL; binary assets (NUL byte) pass through
    byte-for-byte. A file whose only difference from the existing inbox copy is
    its line endings is left untouched, so a no-op pull neither rewrites bytes nor
    churns mtimes (the content-hash cache stays warm — same discipline as the
    publish EOL guard, ``test_realm_sync_eol.py``).
    """

    from ..skill_promotion import is_windows_reserved_component

    # First pass: collect legal source files and the set of top-level package
    # families that contain a reserved-device-name component anywhere in their
    # subtree. Any file under such a family is skipped BEFORE a write is attempted
    # (creating a dir/file named ``con`` on Windows fails), and the whole family
    # is quarantined out so a package is never partially mirrored.
    reserved_tops: set[str] = set()
    candidates: list[tuple[tuple[str, ...], Path]] = []
    if source_skills.is_dir():
        for src in sorted(p for p in source_skills.rglob("*") if p.is_file()):
            rel_parts = src.relative_to(source_skills).parts
            # Untrusted remote tree: a mirror path must never escape the inbox
            # (rglob cannot emit ``..``, but guard defensively regardless).
            if any(part in ("", ".", "..") for part in rel_parts):
                continue
            if any(is_windows_reserved_component(part) for part in rel_parts):
                reserved_tops.add(rel_parts[0])
                continue
            candidates.append((rel_parts, src))

    desired: dict[str, bytes] = {}
    tombstoned_slugs: set[str] = set()
    tombstoned_tops: set[str] = set()
    for rel_parts, src in candidates:
        # A sibling file of a reserved path within the same top-level family is
        # dropped too, so the family is quarantined whole (never half-written).
        if rel_parts[0] in reserved_tops:
            continue
        if tombstoned is not None:
            slug = _subtree_package_slug(source_skills, rel_parts)
            if slug is not None and tombstoned(slug):
                tombstoned_slugs.add(slug)
                tombstoned_tops.add(rel_parts[0])
                continue
        desired["/".join(rel_parts)] = _canonicalize_text_bytes(src.read_bytes())

    existing: dict[str, bytes] = {}
    if inbox.is_dir():
        for path in sorted(p for p in inbox.rglob("*") if p.is_file()):
            existing[path.relative_to(inbox).as_posix()] = path.read_bytes()

    desired_top = {rel.split("/", 1)[0] for rel in desired}
    existing_top = {rel.split("/", 1)[0] for rel in existing}
    # A tombstoned package the inbox still held IS unlinked below, but it is
    # reported as ``tombstoned``, not as ``removed`` — the realm did not stop
    # publishing it, a member deleted it.
    removed = sorted(existing_top - desired_top - reserved_tops - tombstoned_tops)

    for rel, data in desired.items():
        prior = existing.get(rel)
        if prior is not None and _canonicalize_text_bytes(prior) == data:
            continue  # EOL-only (or no) difference — leave it to avoid churn
        target = inbox.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    for rel in existing:
        if rel not in desired:
            inbox.joinpath(*rel.split("/")).unlink()
    _prune_empty_dirs(inbox)
    return removed, sorted(reserved_tops), sorted(tombstoned_slugs)


def _prune_empty_dirs(root: Path) -> None:
    """Remove now-empty subdirectories left behind by inbox pruning (deepest
    first). ``root`` itself is preserved even when empty — it is the realm's
    inbox anchor."""

    if not root.is_dir():
        return
    for directory in sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass  # not empty (or vanished) — leave it


def _held_skill_packages_for_realm(realm: Realm) -> list[str]:
    """``skills_drift`` = this realm's inbox packages that CONFLICT — and since
    2026-09-12 that means conflicts ONLY.

    Scans this realm's resolver-invisible inbox and returns the sorted slugs whose
    THREE-WAY verdict is ``held``: both my copy and the realm's moved since the
    baseline. That is the set an operator must choose a DIRECTION for
    (``realm sync resolve --key skill::<slug> --take local|remote``).

    **It reads the same classifier the pull loop decides through**
    (``skill_sync.classify_inbox_package``, reached here through
    ``list_inbox_packages``' additive ``decision`` column), and that is the
    load-bearing property rather than a tidiness one: while this read filtered
    ``action == "hold_divergent"`` it reported as held every realm-side update for
    every member who merely OWNED the skill, and every local edit — so the sheet's
    held card and the pull's own ``skill_sync`` could disagree, and did. One
    function, one answer.

    Redefines
    the historic drift meaning (formerly a source-vs-destination byte compare over
    publish artifacts, which was structurally always empty since publish source
    and destination were the same canonical file) while keeping the sidecar/result
    key name and ``list[str]`` shape stable (Launcher realm-sync sheet compat)."""

    from ..skill_promotion import list_inbox_packages
    from ..skill_sync import BUCKET_HELD

    return sorted(
        {
            row["skill"]
            for row in list_inbox_packages(realm.id)
            if row["decision"] == BUCKET_HELD
        }
    )
