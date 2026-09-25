"""Which skills a persona can reach: the resolver, the accessible set, the installed catalog memo.

Separate because it walks the skill roots on disk (the build's costliest read)
behind one TTL memo.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from ..persona_assignments import safe_assignment_token
from .context_budget import _profile_snapshot_skill_names
from .spans import _SPAN_CATALOG_WALK, _SPAN_SHARED_CATALOG, _accumulate_span, _note_catalog_walk

__layer__ = "stores"
__all__ = [
    "_SkillObservabilityResolver",
    "_accessible_skills_context",
    "_persona_skill_assignment_removals",
    "_installed_skill_catalog",
    "_skill_candidate_content_hash",
]


class _SkillObservabilityResolver:
    """Build-scoped skill registry + content-receipt cache.

    ``resolve_skill`` intentionally performs an exhaustive collision-safe walk.
    Calling it in a nested persona×skill loop turned one snapshot into hundreds
    of recursive walks.  This resolver preserves the exact same authoritative
    resolver semantics through ``resolve_skills`` while batching every name
    known for one effective root set.  A different profile/root set gets an
    isolated registry entry; package hashes are memoized only for this build.
    """

    def __init__(self, *, root_registries: dict[str, Any] | None = None) -> None:
        self._resolutions_by_roots: dict[tuple[str, ...], dict[str, Any]] = {}
        self._hashes: dict[tuple[str, str], str | None] = {}
        self._skill_contexts: dict[
            tuple[Any, ...],
            tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]],
        ] = {}
        self._shared_catalog: dict[str, dict[str, Any]] | None = None
        self._realm_rows: list[dict[str, Any]] | None = None
        self._root_registries = root_registries if root_registries is not None else {}

    def skill_context(
        self, key: tuple[Any, ...]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]] | None:
        return self._skill_contexts.get(key)

    def remember_skill_context(
        self,
        key: tuple[Any, ...],
        *,
        accessible_skills: list[dict[str, Any]],
        available_skills: list[dict[str, Any]],
        assignment_removals: list[str],
    ) -> None:
        self._skill_contexts[key] = (
            accessible_skills,
            available_skills,
            assignment_removals,
        )

    def shared_catalog(self) -> dict[str, dict[str, Any]]:
        """Build-scoped ``{slug: catalog_row}`` for the canonical shared skills
        root.  ``build_shared_catalog`` walks + content-hashes every shared skill;
        without this memo it re-ran once per projected persona (measured 12× per
        build, 2026-07-23).  Read-only for callers — the same dict is shared."""
        if self._shared_catalog is None:
            catalog: list[dict[str, Any]] = []
            # Stage 6 item 2: the content-hash walk, billed where it runs. On a
            # TURN this memo never hits — the turn lane constructs a fresh
            # resolver per call — so this span is the whole of it every time,
            # which is the fact §0.3 measured at 336 ms cold and Stage 8 fixes.
            with _accumulate_span(_SPAN_SHARED_CATALOG):
                try:
                    from ..skills_inventory import build_shared_catalog

                    _, _, catalog = build_shared_catalog()
                except Exception:
                    catalog = []
            self._shared_catalog = {
                str(item.get("slug") or ""): item
                for item in catalog
                if isinstance(item, dict)
            }
        return self._shared_catalog

    def realm_publish_states(self) -> list[dict[str, Any]]:
        """Build-scoped realm publish/drift rows.  ``build_realm_publish_states``
        also re-ran once per projected persona; memoize it for the build."""
        if self._realm_rows is None:
            try:
                from ..skills_inventory import build_realm_publish_states

                self._realm_rows = build_realm_publish_states()
            except Exception:
                self._realm_rows = []
        return self._realm_rows

    def resolve(self, identifiers: Iterable[str]) -> dict[str, Any]:
        from agent.skill_utils import get_all_skills_dirs
        from agent_runtime.skill_resolution import resolve_skills

        names = list(
            dict.fromkeys(
                str(item or "").strip() for item in identifiers if str(item or "").strip()
            )
        )
        if not names:
            return {}
        roots = list(get_all_skills_dirs())
        root_key = tuple(str(root.resolve()) for root in roots)
        cached = self._resolutions_by_roots.get(root_key, {})
        if root_key not in self._resolutions_by_roots:
            names = list(dict.fromkeys([
                *names,
                *(
                    safe_assignment_token(item.get("name"))
                    for item in _installed_skill_catalog()
                    if isinstance(item, dict)
                    and safe_assignment_token(item.get("name"))
                ),
            ]))
        missing = [name for name in names if name not in cached]
        if missing:
            # Rebuild the root-local registry for the union.  This stays one
            # filesystem walk and keeps collision results deterministic if a
            # later persona introduces a name absent from the first subset.
            requested = list(dict.fromkeys([*cached.keys(), *missing]))
            cached = resolve_skills(
                requested,
                roots=roots,
                _root_registries=self._root_registries,
            )
            self._resolutions_by_roots[root_key] = cached
        return {name: cached[name] for name in names if name in cached}

    def content_hash(self, candidate: Any | None) -> str | None:
        if candidate is None:
            return None
        from agent_runtime.skill_resolution import skill_package_content_hash

        key = (str(candidate.skill_dir or ""), str(candidate.skill_md))
        if key not in self._hashes:
            self._hashes[key] = skill_package_content_hash(
                candidate.skill_dir, candidate.skill_md
            )
        return self._hashes[key]


def _accessible_skills_context(
    persona: Any,
    profile: str,
    *,
    loaded_skill_names: set[str] | None = None,
    queued_skill_names: set[str] | None = None,
    instance_override_names: set[str] | None = None,
    skill_resolver: _SkillObservabilityResolver | None = None,
) -> list[dict[str, Any]]:
    """Redaction-safe list of skills accessible to this persona/profile.

    Reports skill *identity* and install/hash status (names only — never SKILL.md
    bodies). Hash-tracked harness skills surface drift; the rest are reported as
    accessible so Mission Control can distinguish the catalog from actual
    turn-level skill use.
    Falls back to the profile skills snapshot when the persona declares none.
    """
    declared = [str(item).strip() for item in (getattr(persona, "skills", None) or []) if str(item).strip()]
    source_label = "persona_definition"
    if not declared:
        declared = _profile_snapshot_skill_names(profile)
        source_label = "profile_skills_snapshot"
    if not declared:
        return []
    explicit_additions: set[str] = set()
    try:
        from ..config import load_agent_runtime_config

        cfg = load_agent_runtime_config()
        overrides = (getattr(cfg, "personas", {}) or {}).get(
            str(getattr(persona, "id", "")), {}
        )
        if isinstance(overrides, dict):
            raw_additions = overrides.get("skills") or []
            if isinstance(raw_additions, str):
                try:
                    decoded = json.loads(raw_additions)
                    raw_additions = decoded if isinstance(decoded, list) else [raw_additions]
                except Exception:
                    raw_additions = [raw_additions]
            explicit_additions = {str(item).strip() for item in raw_additions}
    except Exception:
        pass
    tracked: set[str] = set()
    mismatched: set[str] = set()
    # Resolve the persona's OWN profile home so skill hash/missing checks run against
    # the profile the persona actually runs on — mirroring profile_readiness (the
    # authoritative surface). Without hermes_home these checks fall back to the active
    # HERMES_HOME, so an isolated persona (e.g. base, whose home differs from the active
    # profile) shows a false hash_mismatch in the HUD while `harness status` reports
    # clean. Keep the None fallback (legacy behavior) when the home can't be resolved.
    profile_home = None
    try:
        from ..profile_context import resolve_persona_profile

        binding = resolve_persona_profile(persona)
        profile_home = getattr(binding, "profile_home", None)
    except Exception:
        profile_home = None
    try:
        from ..skill_install import HARNESS_SKILLS, harness_skill_hash_mismatches

        tracked = {name for name in declared if name in HARNESS_SKILLS}
        mismatched = set(harness_skill_hash_mismatches(sorted(tracked), hermes_home=profile_home))
    except Exception:
        pass
    from agent_runtime.skill_resolution import (
        resolve_skills,
        skill_runtime_compatibility,
    )

    skills: list[dict[str, Any]] = []
    loaded_skill_names = loaded_skill_names or set()
    queued_skill_names = queued_skill_names or set()
    instance_override_names = instance_override_names or set()
    bounded_declared = declared[:80]
    resolutions = (
        skill_resolver.resolve(bounded_declared)
        if skill_resolver is not None
        else resolve_skills(bounded_declared)
    )
    for name in bounded_declared:
        token = safe_assignment_token(name) or name
        resolution = resolutions.get(name)
        if resolution is None:
            continue
        selected = resolution.candidate
        compatibility = skill_runtime_compatibility(
            selected, surface="mission_chat", root_node_mode=False
        )
        assignment_policy = (
            "instance_override"
            if token in instance_override_names
            else "explicit_addition"
            if name in explicit_additions
            else str(compatibility.get("load_policy") or "recommended")
        )
        load_state = (
            "loaded_this_turn"
            if token in loaded_skill_names
            else "queued_next_turn"
            if token in queued_skill_names
            else "assigned_not_loaded"
        )
        if resolution.status != "resolved":
            status = resolution.status
        elif name in mismatched:
            status = "hash_mismatch"
        else:
            status = load_state
        content_hash = (
            skill_resolver.content_hash(selected)
            if skill_resolver is not None
            else _skill_candidate_content_hash(selected)
        )
        skills.append(
            {
                "name": token,
                "kind": "skill",
                "status": status,
                "hash_tracked": content_hash is not None,
                "source": (
                    "persona_instance" if token in instance_override_names else source_label
                ),
                "assignment_source": (
                    "persona_instance" if token in instance_override_names else source_label
                ),
                "assignment_policy": assignment_policy,
                "load_state": load_state,
                "resolution_status": resolution.status,
                "source_kind": selected.source_kind if selected else None,
                "content_hash": content_hash,
                "candidate_count": len(resolution.candidates),
                "compatibility": compatibility,
            }
        )
    return skills


def _persona_skill_assignment_removals(persona: Any) -> list[str]:
    try:
        from ..config import load_agent_runtime_config

        cfg = load_agent_runtime_config()
        overrides = (getattr(cfg, "personas", {}) or {}).get(
            str(getattr(persona, "id", "")), {}
        )
        raw = overrides.get("skills_remove") if isinstance(overrides, dict) else []
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
                raw = decoded if isinstance(decoded, list) else [raw]
            except Exception:
                raw = [raw]
        return sorted(
            {
                safe_assignment_token(item)
                for item in raw or []
                if safe_assignment_token(item)
            }
        )
    except Exception:
        return []


# The installed-skill catalog walk parses every SKILL.md frontmatter (~1k
# YAML loads across one snapshot core, measured 2026-07-09), and the core
# asks once per persona chat session (15+ times per build). A short TTL memo
# collapses that to one walk per build. Observability rows only — never
# authority — so a skill installed/removed mid-window simply appears on the
# first core built after the TTL lapses.
_SKILL_CATALOG_TTL_SECONDS = 15.0


_skill_catalog_memo: dict[str, Any] = {"at": 0.0, "rows": None, "walker": None}


def _resolve_skill_walker():
    try:
        from tools.skills_tool import _find_all_skills

        return _find_all_skills
    except Exception:
        return None


def _installed_skill_catalog() -> list:
    """Memo keyed on BOTH the TTL and the walker's identity: a monkeypatched
    or hot-reloaded `skills_tool._find_all_skills` invalidates the memo
    immediately instead of being masked for a TTL window."""
    import time

    walker = _resolve_skill_walker()
    now = time.monotonic()
    if (
        _skill_catalog_memo["rows"] is not None
        and _skill_catalog_memo["walker"] is walker
        and now - _skill_catalog_memo["at"] < _SKILL_CATALOG_TTL_SECONDS
    ):
        return _skill_catalog_memo["rows"]
    # A MISS. Timed here rather than at the call sites because there are three
    # of them and only one of them is in this module's turn-lane builder — see
    # the Stage 6 note at the top of this file.
    rows: list = []
    _note_catalog_walk()
    with _accumulate_span(_SPAN_CATALOG_WALK):
        if walker is not None:
            try:
                installed = walker()
                if isinstance(installed, list):
                    rows = installed
            except Exception:
                rows = []
    _skill_catalog_memo["rows"] = rows
    _skill_catalog_memo["at"] = now
    _skill_catalog_memo["walker"] = walker
    return rows


def _skill_candidate_content_hash(candidate: Any | None) -> str | None:
    if candidate is None:
        return None
    from agent_runtime.skill_resolution import skill_package_content_hash

    return skill_package_content_hash(candidate.skill_dir, candidate.skill_md)
