"""``hermes harness agent list`` / ``set-profile``: the agent-definition rows.

Separate because an agent definition row joins persona, profile and skill
sources, which no other verb family reads together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from collections.abc import Sequence
from pathlib import Path

from hermes_cli.profiles import list_profiles
from agent_runtime.config import (
    ensure_persisted_personas,
    load_agent_runtime_config,
    persona_skill_sources,
)
from agent_runtime.profile_context import active_profile_name
from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import _list_envelope, _object_envelope, _print_stage42, _sort_rows

if TYPE_CHECKING:  # annotation-only
    from agent_runtime.models import AgentPersona

__layer__ = "lanes"
__all__ = [
    "_agent_definition_row",
    "_cmd_agent_list",
    "_cmd_agent_set_profile",
]


def _cmd_agent_list(args) -> int:
    from agent_runtime.persona_profile_binding import binding_index

    rows: list[dict] = []
    if getattr(args, "all_profiles", False):
        for profile in list_profiles():
            try:
                cfg = load_agent_runtime_config(Path(profile.path) / "config.yaml")
                personas = ensure_persisted_personas(cfg)
                skill_sources = persona_skill_sources(cfg)
                # Same asymmetry `ensure_persisted_personas(cfg)` already has:
                # the config side comes from the ENUMERATED profile's
                # config.yaml, the store side from the ACTIVE runtime root
                # (there is one agent store per runtime root, not per profile).
                # The binding columns therefore describe exactly the merge the
                # row above came from.
                bindings = binding_index(cfg)
            except Exception:
                continue
            for persona in personas:
                rows.append(
                    _agent_definition_row(
                        persona,
                        source_profile=profile.name,
                        bindings=bindings,
                        roster=personas,
                        skill_sources=skill_sources,
                    )
                )
    else:
        cfg = load_agent_runtime_config()
        try:
            bindings = binding_index(cfg)
        except Exception:
            bindings = {}
        personas = ensure_persisted_personas(cfg)
        skill_sources = persona_skill_sources(cfg)
        for persona in personas:
            rows.append(
                _agent_definition_row(
                    persona,
                    source_profile=active_profile_name(),
                    bindings=bindings,
                    roster=personas,
                    skill_sources=skill_sources,
                )
            )
    deduped: dict[tuple[str, str | None], dict] = {}
    for row in rows:
        # Dedup on the ENUMERATED Hermes profile the definition was read from,
        # not on `profile` — `profile` is now the agent's own binding, and two
        # agents in different profile homes can legitimately share one binding.
        deduped[(row["id"], row.get("source_profile"))] = row
    # Roster rows are read per enumerated profile, but WHICH agent store they
    # merged against is a property of the resolved runtime root — the envelope
    # says so (`source_profile` alone cannot; see the 2026-08-12 incident).
    envelope = attach_root_observability(
        _list_envelope("agent", _sort_rows(list(deduped.values()), getattr(args, "sort", None)))
    )
    _print_stage42(envelope, args=args)
    return 0


def _agent_definition_row(
    persona: AgentPersona,
    *,
    source_profile: str | None,
    bindings: dict | None = None,
    roster: Sequence[AgentPersona] | None = None,
    skill_sources: dict | None = None,
) -> dict:
    """One `agent list` row.

    ``profile`` is the agent's OWN ``hermes_profile`` binding — the thing the
    column name promises. It used to be filled with ``active_profile_name()``,
    so every row printed the operator's current profile (live evidence
    2026-07-25: all five agents printed ``alice`` both before AND after a real
    rebind — a first-class surface that structurally could not answer the
    question it appeared to answer). The enumeration source keeps its own,
    honestly-named ``source_profile`` column, and the config-vs-store
    disagreement that ``ensure_persisted_personas`` silently resolves
    store-wins is surfaced rather than hidden.

    ``persona_spellings`` and ``skills`` (2026-09-02) make this verb answer the
    question the refusal on ``agent create --persona`` sends an operator here to
    ask. It already enumerated the placeable definitions — that is exactly what
    ``ensure_persisted_personas`` returns — but it named only ONE of the two
    spellings ``--persona`` takes, and the ``profile`` column beside it is the
    persona's binding rather than an accepted argument, which is a column an
    operator can read as the second spelling and be wrong. The list comes from
    :func:`agent_create.accepted_persona_spellings`, the same function the
    refusal's choice list spends, so the verb and the error cannot disagree.
    ``roster`` is this enumeration's OWN batch, because the ``profile:`` spelling
    is offered only for a uniquely-owned profile and ownership is a property of
    the set the row was read from — under ``--all-profiles`` that is the
    enumerated profile's config merge, not the active root's.
    """

    from agent_runtime.agent_create import accepted_persona_spellings

    binding = (bindings or {}).get(persona.id)
    row = {
        "id": persona.id,
        "name": persona.display_name,
        "role": str(persona.role),
        "profile": persona.hermes_profile,
        "persona_spellings": accepted_persona_spellings(persona, list(roster or [persona])),
        "skills": list(getattr(persona, "skills", []) or []),
        # S0a A6c: WHICH tier answered ``skills``, and what the config declared
        # that the store row does not carry. ``ensure_persisted_personas``
        # resolves that disagreement store-wins and said nothing, so a config
        # ``skills:`` addition that never reached a placement was invisible here.
        # Accounting only — this verb writes nothing; ``persona set-skills`` is
        # the store-writing door and keeps its supersede clock.
        **((skill_sources or {}).get(persona.id) or {
            "skills_source": "catalog",
            "catalog_only_skills": [],
        }),
        "source_profile": source_profile,
        "state": "available",
        "updated_at": None,
    }
    if binding is not None:
        row["config_profile"] = binding.config_profile
        row["store_profile"] = binding.store_profile
        row["binding_source"] = binding.source
        row["binding_diverged"] = binding.diverged
    return row


def _cmd_agent_set_profile(args) -> int:
    """`harness agent set-profile` — the ONE persona⇄profile rebind door.

    The parser opts this verb into the ``dry_run`` control explicitly; it is
    READ here and threaded into the store chokepoint, which validates
    fully, writes nothing and emits nothing on a preview. A mutation verb that
    ignores the flag silently mutates on a preview — this repo has shipped that
    bug twice (the 2026-07-17 office verb family).
    """

    from agent_runtime.persona_profile_binding import PersonaProfileRebindError, rebind_persona_profile

    dry_run = bool(getattr(args, "dry_run", False))
    try:
        result = rebind_persona_profile(
            str(getattr(args, "persona_id", "") or ""),
            profile=str(getattr(args, "profile", "") or ""),
            dry_run=dry_run,
            actor=str(getattr(args, "requested_by", None) or "operator"),
        )
    except PersonaProfileRebindError as exc:
        data = {
            "ok": False,
            "error_code": exc.code,
            "error": str(exc),
            **exc.details,
            "dry_run": dry_run,
            "next_expected": "fix the arguments and retry; no agent binding was changed",
        }
        _print_stage42(_object_envelope("agent_profile_rebind", data), args=args, default_output="json")
        return 2
    _print_stage42(_object_envelope("agent_profile_rebind", result), args=args, default_output="json")
    # A partial apply moved the persona authority but stranded projection rows.
    # Placement rows have no self-heal, so exiting 0 would tell a script the
    # binding is fully consistent when it is not.
    return 0 if result.get("ok", True) else 2
