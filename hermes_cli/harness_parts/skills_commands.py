"""Read-side skill verbs: catalog, publishable, inbox, link-external, inventory.

Separate from ``skills_promotion_commands`` because nothing here moves or deletes
a package; the one write (``link-external``) records a pointer.
"""

from __future__ import annotations

from pathlib import Path

from agent_runtime.cli_format import emit_json
from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import _list_envelope, _print_stage42

__layer__ = "lanes"
__all__ = [
    "_cmd_skills_catalog",
    "_cmd_skills_inbox",
    "_cmd_skills_inventory",
    "_cmd_skills_link_external",
    "_cmd_skills_publishable",
    "_rel_to_shared_skills",
]


def _cmd_skills_catalog(args) -> int:
    """S8: resolve one content-addressed skills catalog by hash (frame-evicted)."""

    from agent_runtime.prompt_observability import skills_catalog_by_hash

    content_hash = str(getattr(args, "content_hash", "") or "").strip()
    catalog = skills_catalog_by_hash(content_hash)
    payload = {
        "hash": content_hash,
        "found": catalog is not None,
        "skills": catalog or [],
    }
    if getattr(args, "json", False):
        print(emit_json(payload))
        return 0
    if catalog is None:
        print(f"skills catalog {content_hash}: (not resolvable from persisted contexts)")
        return 0
    print(f"skills catalog {content_hash}: {len(catalog)} skill(s)")
    for skill in catalog:
        if isinstance(skill, dict):
            print(f"  {skill.get('name')} — {skill.get('status', 'accessible')}")
    return 0


def _rel_to_shared_skills(path) -> str | None:
    """Render a shared-skills path relative to the shared root (never leak the
    absolute runtime root). Falls back to the basename for outside paths."""

    if path is None:
        return None
    from agent_runtime.profile_home import get_shared_skills_dir

    path = Path(path)
    try:
        return path.relative_to(get_shared_skills_dir()).as_posix()
    except ValueError:
        return path.name


def _cmd_skills_publishable(args) -> int:
    """Read-only: every resolvable skill package, whether it can reach a realm,
    and — when it cannot be promoted into the shared root — the typed reason.

    Names ALL offenders in one listing with a per-row typed code; a surface that
    reported only the shared root is exactly how "resolvable but structurally
    unable to travel" stayed invisible."""

    from agent_runtime.skill_publishability import build_publishability_rows

    source_kind = str(getattr(args, "source_kind", "") or "").strip() or None
    unpublishable_only = bool(getattr(args, "unpublishable_only", False))

    rows = build_publishability_rows()
    if source_kind is not None:
        rows = [row for row in rows if row["source_kind"] == source_kind]
    if unpublishable_only:
        rows = [row for row in rows if not row["publishable"]]
    _print_stage42(_list_envelope("skill_publishability", rows), args=args, default_output="json")
    return 0


def _cmd_skills_inbox(args) -> int:
    """C4: read-only listing of quarantined per-realm inbox skill packages and
    how each would reconcile against the canonical shared root."""

    from agent_runtime.skill_promotion import list_inbox_packages

    realm_token = str(getattr(args, "realm", "") or "").strip() or None
    rows = list_inbox_packages(realm_token)
    items = [
        {
            "skill": row["skill"],
            "realm": row["realm"],
            "action": row["action"],
            "source_hash": row["source_hash"],
            "canonical_hash": row["canonical_hash"],
            "promotion_block_reason": row["promotion_block_reason"],
            "promotion_block_detail": row["promotion_block_detail"],
            # The THREE-WAY verdict (2026-09-12): ``action`` alone cannot tell a
            # realm-side update (``updated``) from a conflict (``held``) — it has
            # no baseline. Read ``decision``; ``action`` stays because the guarded
            # write door dispatches on it.
            "decision": row["decision"],
            "baseline_hash": row["baseline_hash"],
        }
        for row in rows
    ]
    _print_stage42(_list_envelope("inbox_package", items), args=args, default_output="json")
    return 0


def _cmd_skills_link_external(args) -> int:
    from agent_runtime.external_skill_links import format_report, link_shared_skills_into_external_harnesses

    report = link_shared_skills_into_external_harnesses()
    if getattr(args, "json", False):
        # The shared skills root being linked is resolved from the runtime root,
        # so the envelope states which root answered.
        print(emit_json(attach_root_observability(report.to_dict())))
    else:
        print(format_report(report))
    return 0


def _cmd_skills_inventory(args) -> int:
    from agent_runtime.skills_inventory import build_skills_inventory

    payload = build_skills_inventory()
    if getattr(args, "json", False):
        print(emit_json(payload))
        return 0

    root = payload["shared_root"] or "(none)"
    print(f"Shared skills root: {root}")
    if not payload["skills"]:
        print("  (no shared skills)")
    for skill in payload["skills"]:
        count = skill["file_count"]
        files = f"{count} file" + ("" if count == 1 else "s")
        shadow = f"  shadowed by {', '.join(skill['shadowed_by'])}" if skill["shadowed_by"] else ""
        print(f"  {skill['slug']:<28} {files}{shadow}")
        if skill["description"]:
            print(f"      {skill['description']}")
    print("Personas:")
    for persona in payload["personas"]:
        print(f"  {persona['id']:<16} {len(persona['skills'])} skills")
    print("Realms:")
    for realm in payload["realms"]:
        bound = "server" if realm["server_bound"] else "local"
        state = realm["sync_state"] or "not checked"
        drift = f"  drift: {', '.join(realm['skills_drift'])}" if realm["skills_drift"] else ""
        print(f"  {realm['realm_id']:<20} [{bound}] {state}{drift}")
    return 0
