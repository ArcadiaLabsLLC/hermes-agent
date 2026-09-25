"""The snapshot's ``prompt_observability`` section: ``snapshot_prompt_observability``.

Separate because it is the snapshot lane's entry point, reading the persisted
rows and the HUD rather than building a turn. The section is built by
:class:`SnapshotFrame` in the order it is assembled: the roster, each lane's
HUD and built row, the live-row merge, the hoist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..persona_assignments import (
    is_canonical_persona_channel,
    safe_assignment_text,
    safe_assignment_token,
)
from ..serde import to_jsonable
from .context_budget import _persona_instance_id, _profile_persona_from_instance
from .context_store import (
    _context_row_key,
    _filter_live_chat_contexts,
    _merge_latest_contexts,
    load_live_prompt_observability_contexts,
)
from .hoist import (
    _evict_builder_timings,
    _evict_final_model_input,
    _evict_prompt_layer_content,
    _hoist_skills_catalogs,
)
from .mission_chat import mission_chat_prompt_observability
from .skills_resolver import _SkillObservabilityResolver

__layer__ = "lanes"
__all__ = [
    "SnapshotFrame",
    "snapshot_prompt_observability",
]


# S54 removed ``load_final_model_input_for_context`` and
# ``_mission_chat_template_prompt_chars``: a disk read-back accessor and a
# template-size helper, neither with a production caller.

def snapshot_prompt_observability(
    *,
    personas: Iterable[Any],
    persona_instances: Iterable[Any],
    session_db: Any | None = None,
    daemon: dict[str, Any] | None = None,
    realm: str | None = None,
    workspace: str | None = None,
    active_workspace_id: str | None = None,
    catalog_sink: dict[str, list[dict[str, Any]]] | None = None,
    skill_resolver: "_SkillObservabilityResolver | None" = None,
) -> dict[str, Any]:
    return SnapshotFrame(
        personas=personas,
        persona_instances=persona_instances,
        session_db=session_db,
        daemon=daemon,
        realm=realm,
        workspace=workspace,
        active_workspace_id=active_workspace_id,
        catalog_sink=catalog_sink,
        skill_resolver=skill_resolver,
    ).build()


@dataclass
class SnapshotFrame:
    """One snapshot's ``prompt_observability`` section: roster -> HUD -> live rows -> hoist."""

    personas: Iterable[Any]
    persona_instances: Iterable[Any]
    session_db: Any | None = None
    daemon: dict[str, Any] | None = None
    realm: str | None = None
    workspace: str | None = None
    active_workspace_id: str | None = None
    catalog_sink: dict[str, list[dict[str, Any]]] | None = None
    skill_resolver: "_SkillObservabilityResolver | None" = None
    roster: list[Any] = field(init=False)
    installs: Any = field(init=False)

    def build(self) -> dict[str, Any]:
        self.roster_and_installs()
        contexts = self.built_contexts()
        chat_contexts, chat_contexts_evicted, ctx_read = self.live_rows(contexts)
        frame_catalog_hashes = self.hoist(chat_contexts)
        return self.section(chat_contexts, chat_contexts_evicted, ctx_read, frame_catalog_hashes)

    def roster_and_installs(self) -> None:
        # Deferred import: runtime_hud pulls a sizeable dependency graph, and this
        # module is imported very early. A function-local import keeps module load
        # order robust while still resolving through the single HUD authority.
        from ..runtime_hud import _installs_block

        # S47: the ``tasks`` parameter and the ``tasks_by_id`` index built from it
        # are gone. Its only production caller seeded ``tasks = []``, so every lane
        # resolved ``task=None, goal_task=None`` — a constant dressed as a lookup.
        # S47 recorded that ``resolve_situational_hud`` KEPT ``task``/``goal_task``
        # because the live mission-chat wrapper resolved them from the store per
        # turn. That stopped being true at ``3c3615beb``, which removed both
        # parameters with the retired task HUD — there is no longer anything to
        # pass. Corrected at S66 rather than left asserting a signature this tree
        # does not have.
        # Materialize once: the roster is reused for every lane's situational HUD
        # (thread count + on-level list) and the input may be a one-shot iterable.
        self.roster = list(self.persona_instances)
        self.installs = _installs_block()

    def situational_for(self, instance: Any) -> dict[str, Any]:
        from .. import workspace_scope
        from ..runtime_hud import resolve_situational_hud

        try:
            # Scope the ADDRESSABLE roster to this lane's own workspace so the
            # recorded snapshot advertises the exact same "On level" set the
            # live mission-chat turn feeds — a placement in another workspace
            # must not appear here, runtime-global canonical plumbing rows are
            # excluded (instance = in-level placement), and a surviving
            # canonical row shadowed by an in-scope placement is dropped too
            # (parity envelope). Identity (steering) resolves against the full,
            # unscoped roster, matching the HUD wrapper.
            scope_workspace_id = workspace_scope.effective_workspace_id(
                instance, active_workspace_id=self.active_workspace_id
            )
            scoped_roster = workspace_scope.addressable_roster(
                self.roster,
                scope_workspace_id=scope_workspace_id,
                is_canonical=is_canonical_persona_channel,
            )
            return resolve_situational_hud(
                instance,
                daemon=self.daemon,
                realm=self.realm,
                workspace=self.workspace,
                roster=scoped_roster,
                identity_roster=self.roster,
                # Resolved ONCE per snapshot, outside the per-lane method, for
                # the reason ``roster`` is materialised once above: the block is
                # identical for every lane on this install and re-reading two
                # files per persona would be a cost proportional to a fact that
                # does not vary.
                installs=self.installs,
            )
        except Exception:
            # Same guarantee as the preview: a situational-HUD failure degrades
            # to {} rather than breaking the snapshot.
            return {}

    def built_contexts(self) -> list[dict[str, Any]]:
        from ..models import apply_instance_model_overrides

        contexts: list[dict[str, Any]] = []
        # One build-scoped resolver owns filesystem skill discovery + package hashes
        # for every projected persona.  The active profile context is part of its
        # cache key, so profile-specific roots never bleed into another persona,
        # while the normal shared-install case pays one registry walk for the whole
        # snapshot instead of one recursive walk per skill, per persona.
        skill_resolver = self.skill_resolver or _SkillObservabilityResolver()
        by_persona = {
            safe_assignment_token(getattr(persona, "id", None)): persona
            for persona in self.personas
            if safe_assignment_token(getattr(persona, "id", None))
        }
        for instance in self.roster:
            persona_id = safe_assignment_token(getattr(instance, "persona_id", None))
            persona = by_persona.get(persona_id) or _profile_persona_from_instance(instance)
            if persona is None:
                continue
            effective_persona = apply_instance_model_overrides(persona, instance)
            task_id = getattr(instance, "current_task_id", None)
            contexts.append(
                mission_chat_prompt_observability(
                    persona=effective_persona,
                    persona_instance_id=_persona_instance_id(instance),
                    session_id=getattr(instance, "session_id", None),
                    task_id=task_id,
                    goal_id=getattr(instance, "goal_id", None),
                    surface_prompt="",
                    limiting_wrapper_active=False,
                    session_db=self.session_db,
                    situational_hud=self.situational_for(instance),
                    instance_skill_overrides=(
                        list(getattr(instance, "skill_overrides", None) or [])
                        if getattr(instance, "skill_overrides", None) is not None
                        else None
                    ),
                    skill_resolver=skill_resolver,
                )
            )
        return contexts

    def live_rows(self, contexts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        roster = self.roster
        # S8: the frame keeps only LIVE persona instances' current-session context
        # rows; historical/stale rows (departed instances, closed sessions) leave the
        # frame (operator ruling 2026-07-17: "old residue and runs need to be
        # purged"). The persisted files stay on disk (archive-never-delete); the
        # Context peek only selects a live roster agent, so a dropped row is never
        # requested. ``built_keys`` are the freshly-built roster contexts = the live
        # rows; live instance/session ids catch a live agent whose row came only from
        # disk.
        built_keys = {_context_row_key(item) for item in contexts}
        live_instance_ids = {
            token
            for token in (safe_assignment_token(_persona_instance_id(inst)) for inst in roster)
            if token
        }
        live_session_ids = {
            session
            for session in (
                safe_assignment_text(getattr(inst, "session_id", None), limit=200) for inst in roster
            )
            if session
        }
        # C2: roster-keyed read — the latest-pointer index resolves the live lanes
        # and the build reads exactly those rows (typed glob fallback on index
        # miss/corruption; the read never writes).
        disk_rows, ctx_read = load_live_prompt_observability_contexts(
            built_keys=built_keys,
            live_instance_ids=live_instance_ids,
            live_session_ids=live_session_ids,
        )
        chat_contexts = _merge_latest_contexts(contexts, session_db=self.session_db, disk_rows=disk_rows)
        chat_contexts, chat_contexts_evicted = _filter_live_chat_contexts(
            chat_contexts,
            built_keys=built_keys,
            live_instance_ids=live_instance_ids,
            live_session_ids=live_session_ids,
        )
        # Index-mode reads never load the stale lanes at all — fold them into the
        # same eviction count the post-merge filter feeds (one accounting, both
        # read modes).
        chat_contexts_evicted += int(ctx_read.get("stale_lanes") or 0)
        return chat_contexts, chat_contexts_evicted, ctx_read

    def hoist(self, chat_contexts: list[dict[str, Any]]) -> set[str]:
        # S3: hoist the duplicated skills catalogs to one content-addressed table and
        # evict the heavy per-turn debug payload. This is the only shape (S7-B
        # RULING-0: no inline legacy fallback).
        skills_catalogs: dict[str, Any] = {}
        _hoist_skills_catalogs(chat_contexts, skills_catalogs)
        # The steady-state frame still carries hashes only.  The explicit
        # ``skills catalog --hash`` detail fetch may provide a sink to capture the
        # exact bodies from this same projection and materialize its immutable
        # cache on demand.  A normal snapshot passes no sink and remains write-free.
        if self.catalog_sink is not None:
            for ref, rows in skills_catalogs.items():
                if isinstance(rows, list):
                    self.catalog_sink.setdefault(ref, to_jsonable(rows))
        _evict_final_model_input(chat_contexts)
        # chat-turn-prep Stage 6: the builder's own sub-spans are the turn handler's
        # and nobody else's — least of all a byte-pinned wire projection.
        _evict_builder_timings(chat_contexts)
        # w13/h4: the same move, one field over, to what became the largest slice —
        # the prompt-layer BODIES. The descriptor table stays whole (the row's own
        # re-measurement ruled that cut not worth its churn).
        _evict_prompt_layer_content(chat_contexts)
        # C1: ref-shaped persisted rows reach the frame already carrying their
        # ``*_ref`` hashes (no inline lists for the hoist to fold) — the frame's
        # catalog accounting must include those refs too, or the pointer stub would
        # under-report the resolvable hashes.
        frame_catalog_hashes = set(skills_catalogs)
        for row in chat_contexts:
            if not isinstance(row, dict):
                continue
            for ref_key in ("available_skills_ref", "accessible_skills_ref"):
                token = safe_assignment_token(row.get(ref_key))
                if token:
                    frame_catalog_hashes.add(token)
        return frame_catalog_hashes

    @staticmethod
    def section(
        chat_contexts: list[dict[str, Any]],
        chat_contexts_evicted: int,
        ctx_read: dict[str, Any],
        frame_catalog_hashes: set[str],
    ) -> dict[str, Any]:
        # S8: the ``skills_catalogs`` table LEAVES the frame entirely (operator ruling
        # 2026-07-17: "skills catalog should just be pointers to the skills"). Rows
        # keep their ``*_ref`` content hashes; the catalog bodies are served on demand
        # by ``harness skills catalog --hash <h> --json`` and cached FOREVER launcher
        # side (a content hash is immutable). The frame carries only a typed pointer
        # stub (count + fetch verb) — never a silent absence.
        return {
            "schema_version": 1,
            "surface_prompt_default": "",
            "chat_contexts": chat_contexts,
            # S8: honest accounting for the historical/stale context rows evicted
            # from the frame — their persisted files remain on disk and are fetched
            # on demand (never a silent absence). C2 adds the retention accounting
            # (``archived_count``: rows MOVED to the archive dir, still fetchable)
            # and the typed read receipt (index hit vs glob fallback — a degraded
            # read is visible, never silent).
            "chat_contexts_ref": {
                "evicted": True,
                "count": chat_contexts_evicted,
                "live_count": len(chat_contexts),
                "archived_count": int(ctx_read.get("archived_count") or 0),
                "fetch": "harness prompt-context show --context-id <id> --json",
                "read": {
                    "source": ctx_read.get("source"),
                    "index_status": ctx_read.get("index_status"),
                    "files_read": int(ctx_read.get("files_read") or 0),
                    "index_misses": int(ctx_read.get("index_misses") or 0),
                },
            },
            # One fact, one owner, one COPY: the deduplicated skill lists are no
            # longer shipped in-frame. Rows carry ``available_skills_ref`` /
            # ``accessible_skills_ref``; the bodies are content-addressed and fetched
            # once by hash. This pointer accounts the eviction (hoist-folded catalogs
            # plus the refs already carried by C1 ref-shaped persisted rows).
            "skills_catalogs_ref": {
                "evicted": True,
                "count": len(frame_catalog_hashes),
                "hashes": sorted(frame_catalog_hashes),
                "fetch": "harness skills catalog --hash <hash> --json",
            },
        }
