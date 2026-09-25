"""``RealmStore`` — create / save / archive / bind_server, the two publish
selections, the skill tombstone and its restore, and set_active.
"""

from __future__ import annotations

import uuid

from hermes_time import now

from .. import paths
from ..errors import AlreadyExists, SkillTombstoneRefused
from ..events import EventLog
from ..models import (
    Realm,
    SkillTombstone,
    validate_agent_publish_mode,
    validate_skill_publish_mode,
)
from ..serde import safe_id
from ..store_events import emit_store_event
from .base import (
    _list_models,
    _read_model,
    _safe_display_name,
    _slugify,
    _write_model,
    apply_activation,
    read_pointer,
)
from .ledgers import (
    _normalize_agent_selection,
    _normalize_skill_selection,
    _prune_skill_tombstones,
    active_skill_tombstones,
    skill_tombstone_matches,
)

__layer__ = "stores"


class RealmStore:
    def __init__(self, event_log: EventLog | None = None):
        self.event_log = event_log or EventLog()

    def create(
        self,
        *,
        name: str,
        server_id: str | None = None,
        realm_id: str | None = None,
        default_workspace_id: str | None = None,
        default_workspace_name: str = "Default",
        default_workspace_version: int = 0,
    ) -> Realm:
        clean_name = _safe_display_name(name)
        if not clean_name:
            raise ValueError("realm name is required")
        ts = now()
        slug = _slugify(clean_name)
        item = Realm(
            id=safe_id(realm_id) or f"realm_{slug}_{uuid.uuid4().hex[:6]}",
            slug=slug,
            name=clean_name,
            server_id=safe_id(server_id),
            default_workspace_id=safe_id(default_workspace_id),
            default_workspace_name=_safe_display_name(default_workspace_name) or "Default",
            default_workspace_version=max(0, int(default_workspace_version)),
            created_at=ts,
            updated_at=ts,
        )
        path = paths.realm_path(item.id)
        if path.exists():
            raise AlreadyExists(item.id)
        _write_model(path, item)
        emit_store_event(
            self.event_log,
            "realm.created",
            {"realm_id": item.id, "name": item.name, "server_id": item.server_id},
            domain="store",
        )
        return self.get(item.id)

    def get(self, realm_id: str) -> Realm:
        return _read_model(Realm, paths.realm_path(realm_id))

    def list_all(self, *, include_archived: bool = False) -> list[Realm]:
        items = _list_models(Realm, paths.realms_dir())
        if not include_archived:
            items = [item for item in items if not item.archived]
        return sorted(items, key=lambda item: (item.name.lower(), item.id))

    def save(self, item: Realm, *, emit_event: bool = True) -> Realm:
        """``emit_event=False`` is for callers that append their own, more
        specific event in the same mutation (bind_server, realm adopt)."""
        item.updated_at = now()
        _write_model(paths.realm_path(item.id), item)
        if emit_event:
            emit_store_event(
                self.event_log,
                "realm.updated",
                {"realm_id": item.id, "change": "saved"},
                domain="store",
            )
        return self.get(item.id)

    def archive(self, realm_id: str) -> Realm:
        """Recoverably remove a Realm from live selectors and projections."""

        item = self.get(realm_id)
        if item.archived:
            return item
        item.archived = True
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "realm.archived",
            {"realm_id": item.id, "name": item.name},
            domain="store",
        )
        return item

    def bind_server(self, realm_id: str, server_id: str) -> Realm:
        item = self.get(realm_id)
        item.server_id = safe_id(server_id)
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "realm.updated",
            {"realm_id": item.id, "change": "server_bound", "server_id": item.server_id},
            domain="store",
        )
        return item

    def set_skill_selection(
        self, realm_id: str, *, mode: str, selection: list[str], dry_run: bool = False
    ) -> Realm:
        """Single write chokepoint for a realm's shared-skill publish selection.

        ``mode == "all"`` publishes every shared skill and PRESERVES the stored
        ``skill_selection`` intact (switching back to "selected" restores it, so
        the passed ``selection`` is ignored in this mode). ``mode == "selected"``
        replaces the selection with the validated/deduped/sorted slugs (an empty
        list means "publish none").

        Slugs are validated for shape only (non-empty, no leading dot, no path
        separators, must equal their ``safe_path_token`` form). Slugs unknown to
        this machine's catalog are NOT filtered here — another member may hold
        the skill locally, and dropping it on an unrelated save would corrupt
        realm truth; unknown slugs are reported (``missing``) by the CLI, never
        stripped. Emits ``realm.updated``/``skill_selection`` so the read-model
        pipeline sees the mutation (Stage 12 watermark discipline).

        ``dry_run`` runs the full validation and returns the WOULD-BE realm
        (in-memory only) without saving and without emitting the store event.
        """
        validate_skill_publish_mode(mode)
        item = self.get(realm_id)
        if mode == "selected":
            item.skill_selection = _normalize_skill_selection(selection)
        item.skill_publish_mode = mode
        if dry_run:
            return item
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "realm.updated",
            {
                "realm_id": item.id,
                "change": "skill_selection",
                "mode": mode,
                "selection_count": len(item.skill_selection),
            },
            domain="store",
        )
        return item

    def tombstone_skill(
        self,
        realm_id: str,
        slug: str,
        *,
        deleted_hash: str | None = None,
        dry_run: bool = False,
    ) -> Realm:
        """Single write chokepoint for a realm's shared-skill delete ledger.

        Records realm-wide intent: "this skill is deleted, not merely
        unpublished here". Without the distinction, narrowing
        ``skill_selection`` would be indistinguishable from a delete and would
        destroy members' local copies that were never meant to die.

        Refusals are typed (:class:`~.errors.SkillTombstoneRefused`) and raised
        BEFORE any mutation:

        - ``skill_slug_invalid`` — shape refusal from the promotion door's own
          validator, so a delete and a promotion share one alphabet.
        - ``skill_installer_owned`` — ``CANONICAL_SHARED_SKILL_IDS`` are
          reinstalled from repo source on every pull; a ledger entry for one
          would lose that argument forever, so the door names the real delete
          lane instead of minting a tombstone that does nothing.

        Re-tombstoning an already-listed slug REPLACES the entry (one entry per
        slug), which refreshes ``deleted_at`` and clears any ``restored_at``
        from an earlier lift — the register records the CURRENT state, never a
        delete stamp sitting beside a stale restore stamp. The list is bounded
        through :func:`prune_settled_ledger`, so settled (restored) history is
        evicted before any live block. The slug is also pruned from ``skill_selection`` at the
        same write — a selection naming a tombstoned slug is a standing
        contradiction — using the ``skill_tombstoned`` match rule, so a
        categorized ``<cat>/<child>`` selection entry blocked by a bare-name
        tombstone goes too. ``restore_skill`` does NOT re-add it: selection is a
        separate, deliberate act (``realm skills set``).

        ``dry_run`` runs the full validation and returns the WOULD-BE realm
        (in-memory only) without saving and without emitting the store event.
        """
        from agent_runtime.profile_home import CANONICAL_SHARED_SKILL_IDS

        from ..skill_promotion import validate_skill_slug

        clean = str(slug or "").strip()
        reason = validate_skill_slug(clean)
        if reason is not None:
            raise SkillTombstoneRefused(
                "skill_slug_invalid",
                f"{clean!r} is not a valid skill slug: {reason}",
                safe_details={"slug": clean},
            )
        if clean in CANONICAL_SHARED_SKILL_IDS:
            raise SkillTombstoneRefused(
                "skill_installer_owned",
                (
                    f"{clean!r} is a hermes-installed harness skill: every realm pull "
                    "reinstalls it from repo source, so a realm tombstone can never "
                    "hold. Delete it from agent_runtime.profile_home.CANONICAL_SHARED_SKILL_IDS "
                    "and docs/agent-runtime-harness/harness-skills/ instead."
                ),
                safe_details={"slug": clean},
            )

        item = self.get(realm_id)
        ledger = [
            entry for entry in (item.skill_tombstones or []) if entry.slug != clean
        ]
        ledger.append(SkillTombstone(slug=clean, deleted_at=now(), deleted_hash=deleted_hash))
        item.skill_tombstones = _prune_skill_tombstones(ledger)
        item.skill_selection = [
            value
            for value in (item.skill_selection or [])
            if not skill_tombstone_matches(clean, value)
        ]
        if dry_run:
            return item
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "realm.updated",
            {"realm_id": item.id, "change": "skill_tombstoned", "slug": clean},
            domain="store",
        )
        return item

    def restore_skill(self, realm_id: str, slug: str, *, dry_run: bool = False) -> Realm:
        """Lift ONE ledger entry — the explicit door out of a skill tombstone.

        Names a LEDGER ENTRY, not a package: the entry whose ``slug`` matches
        exactly is lifted, which is what ``realm skills show`` lists. (A
        categorized package blocked by a bare-name tombstone is restored by
        naming that bare name.) Restoring content is the separate, existing
        lane — ``skills promote --from-path shared/skills/.archive/<ts>/<slug>``,
        or a fresh publish from a member who still holds it.

        The lift STAMPS ``restored_at`` rather than removing the entry (RD-11).
        A removal is an absence, and the pull-time union merge cannot tell an
        absence that means "restored here" from one that means "this member
        never heard about the delete" — so under a union every restore would be
        undone by the next pull from a member who still held the tombstone. The
        marker is a fact that can win the merge on its own timestamp. The entry
        stops blocking the moment it is stamped (:func:`active_skill_tombstones`),
        which is what every enforcement point and receipt reads.

        Idempotent: an absent entry — or one already lifted — is not an error
        and writes nothing (a no-op mutation must not emit an event either — the
        watermark advances only for real writes). Callers report ``restored`` by
        asking the ACTIVE ledger first.
        """
        clean = str(slug or "").strip()
        item = self.get(realm_id)
        lifted = next(
            (entry for entry in active_skill_tombstones(item) if entry.slug == clean),
            None,
        )
        if lifted is None:
            return item
        lifted.restored_at = now()
        item.skill_tombstones = _prune_skill_tombstones(item.skill_tombstones or [])
        if dry_run:
            return item
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "realm.updated",
            {"realm_id": item.id, "change": "skill_tombstone_restored", "slug": clean},
            domain="store",
        )
        return item

    def set_agent_selection(
        self, realm_id: str, *, mode: str, selection: list[str], dry_run: bool = False
    ) -> Realm:
        """Single write chokepoint for Realm persona-definition selection.

        ``workspace`` keeps the explicit list intact but publishes only the
        definitions required by synced workspace/Office references.
        ``selected`` publishes the explicit set plus those required references.
        Unknown persona ids are preserved and reported by the CLI envelope.
        """
        validate_agent_publish_mode(mode)
        item = self.get(realm_id)
        if mode == "selected":
            item.agent_selection = _normalize_agent_selection(selection)
        item.agent_publish_mode = mode
        if dry_run:
            return item
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "realm.updated",
            {
                "realm_id": item.id,
                "change": "agent_selection",
                "mode": mode,
                "selection_count": len(item.agent_selection),
            },
            domain="store",
        )
        return item

    def set_active(self, realm_id: str | None, *, issued_at: str | None = None) -> dict:
        value = safe_id(realm_id)
        name = self.get(value).name if value else None
        return apply_activation(
            paths.active_realm_path(),
            "realm_id",
            value,
            issued_at,
            name=name,
            event_type="realm.activated",
            event_log=self.event_log,
        )

    def active_id(self) -> str | None:
        return read_pointer(paths.active_realm_path(), "realm_id")
