"""The situational HUD itself: resolved from loaded facts, then rendered as the hashed body.

``resolve_situational_hud`` assembles the typed snapshot (pure — no I/O) from
the lane, mission, roster, residency stamp, steering, board, budget and
capability facts; ``render_situational_hud_block`` renders the ``## Runtime
Situation`` block from ``fields.stable_hud_fields`` only, with the handle /
install / age phrasings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from agent_runtime.clock import parse_iso_utc
from agent_runtime.models import looks_like_persona_instance_id
from agent_runtime.serde import optional_text

from agent_runtime.runtime_hud.fields import (
    CAPABILITY_HUD_KEY,
    SITUATIONAL_HUD_ROSTER_CAP,
    section,
    stable_hud_fields,
)

__layer__ = "policy"


def _clean(value: Any) -> bool:
    """True when a value carries information worth emitting."""

    return value not in (None, "", [], {})


def _lane_block(instance: Any) -> dict[str, Any]:
    if instance is None:
        return {}
    lane = {
        "display_name": optional_text(getattr(instance, "display_name", None)),
        "persona_instance_id": optional_text(getattr(instance, "id", None)),
        "persona_id": optional_text(getattr(instance, "persona_id", None)),
        "role": optional_text(getattr(instance, "role", None)),
        "mode": optional_text(getattr(instance, "mode", None)),
        "state": optional_text(getattr(instance, "state", None)),
        "goal_id": optional_text(getattr(instance, "goal_id", None)),
        "current_task_id": optional_text(getattr(instance, "current_task_id", None)),
    }
    return {key: value for key, value in lane.items() if _clean(value)}


def _mission_block(
    instance: Any,
    *,
    roster: Iterable[Any],
) -> dict[str, Any]:
    goal_id = optional_text(getattr(instance, "goal_id", None))
    if goal_id is None:
        return {}
    mission = {
        "goal_id": goal_id,
        "thread_count": _thread_count(goal_id, roster),
    }
    return {key: value for key, value in mission.items() if _clean(value)}


def _thread_count(goal_id: str | None, roster: Iterable[Any]) -> int | None:
    if not goal_id:
        return None
    count = 0
    for inst in roster or ():
        if optional_text(getattr(inst, "goal_id", None)) == goal_id:
            count += 1
    return count or None


def _roster_block(roster: Iterable[Any], *, self_id: str | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for inst in roster or ():
        instance_id = optional_text(getattr(inst, "id", None))
        if instance_id is None:
            continue
        entry: dict[str, Any] = {
            "display_name": optional_text(getattr(inst, "display_name", None)) or instance_id,
            "persona_instance_id": instance_id,
        }
        if self_id is not None and instance_id == self_id:
            entry["is_self"] = True
        entries.append(entry)
        if len(entries) >= SITUATIONAL_HUD_ROSTER_CAP:
            break
    return entries


def _stamp_residency(
    roster_block: list[dict[str, Any]], installs: list[dict[str, Any]]
) -> None:
    """Mark each local entry that also appears in a CACHED far roster.

    Matched on ``persona_instance_id`` — the handle, which is minted once and is
    the same string on both machines when an instance was replicated — rather
    than on the display name, which two unrelated agents can share. A name match
    here would produce a residency claim that is simply wrong, and a wrong claim
    in a HUD is worse than an absent one because an agent acts on it.

    Mutates in place because it is decorating the block that is about to be
    rendered, and returns nothing so no caller mistakes it for a projection.
    """

    by_handle: dict[str, list[dict[str, Any]]] = {}
    for install in installs:
        for row in install.get("roster") or ():
            handle = str((row or {}).get("handle") or "").strip()
            if not handle:
                continue
            by_handle.setdefault(handle, []).append(
                {"ref": install.get("ref"), "last_turn_at": row.get("last_turn_at")}
            )
    for entry in roster_block:
        elsewhere = by_handle.get(str(entry.get("persona_instance_id") or ""))
        if elsewhere:
            entry["also_on"] = elsewhere


def _parent_refs(instance: Any) -> list[str]:
    """The steering-parent ref set of an instance (fan-in aware): the
    authoritative ``steered_by`` list, falling back to ``[spawned_by]`` for
    un-migrated records. Mirrors the launcher's
    ``missionAgentInstanceParentIds`` so both ends agree who steers whom.

    Raw refs — a ref may name an instance id, a persona id, or a role, resolved
    downstream in :func:`_steering_block`. Principals that resolve to nobody AND
    are not instance-shaped (the operator) are dropped there, not here, so the
    intentional persona/role resolution is preserved."""

    refs = [ref for ref in (optional_text(item) for item in (getattr(instance, "steered_by", None) or ())) if ref]
    if refs:
        return refs
    spawned_by = optional_text(getattr(instance, "spawned_by", None))
    return [spawned_by] if spawned_by else []


def _resolve_parent_ref(ref: str, roster: Iterable[Any]) -> Any | None:
    """Resolve a parent ref to a roster instance. A ref may name an instance id,
    a persona id, or a role — in that precedence order (mirrors the launcher's
    ``missionAgentOwnerForSpawnedBy``)."""

    by_persona = None
    by_role = None
    for inst in roster or ():
        if optional_text(getattr(inst, "id", None)) == ref:
            return inst
        if by_persona is None and optional_text(getattr(inst, "persona_id", None)) == ref:
            by_persona = inst
        if by_role is None and optional_text(getattr(inst, "role", None)) == ref:
            by_role = inst
    return by_persona or by_role


def _steering_block(instance: Any, roster: Iterable[Any], *, self_id: str | None) -> dict[str, Any]:
    """Who steers this lane, and whom it steers — harness truth, fan-in aware.

    Hermes states steering only child→parent (``steered_by``/``spawned_by``), so
    the downstream set is derived by inverting the roster through the same ref
    resolution, keeping both directions consistent. Both keys are ALWAYS present:
    explicit empty lists mean genuinely standalone (the common case), which a
    consumer must be able to tell apart from "this hermes predates steering"."""

    roster = list(roster or ())
    steered_by: list[dict[str, Any]] = []
    for ref in _parent_refs(instance):
        parent = _resolve_parent_ref(ref, roster)
        # Drop a phantom steerer: a ref that resolves to nobody AND is not even
        # instance-shaped is a non-agent principal (the operator, leaked into a
        # steering field by a legacy mint), never a real steer parent — so the
        # HUD must not narrate "steered by operator". A resolved persona/role ref,
        # or an instance-shaped-but-departed ref ("off level"), is a genuine fact
        # and is kept.
        if parent is None and not looks_like_persona_instance_id(ref):
            continue
        entry: dict[str, Any] = {"ref": ref}
        if parent is not None:
            entry["persona_instance_id"] = optional_text(getattr(parent, "id", None))
            entry["display_name"] = optional_text(getattr(parent, "display_name", None)) or ref
        steered_by.append(entry)

    steers: list[dict[str, Any]] = []
    for inst in roster:
        instance_id = optional_text(getattr(inst, "id", None))
        if instance_id is None or instance_id == self_id:
            continue
        for ref in _parent_refs(inst):
            parent = _resolve_parent_ref(ref, roster)
            if parent is not None and optional_text(getattr(parent, "id", None)) == self_id:
                steers.append(
                    {
                        "persona_instance_id": instance_id,
                        "display_name": optional_text(getattr(inst, "display_name", None)) or instance_id,
                    }
                )
                break

    return {"steered_by": steered_by, "steers": steers}


def resolve_situational_hud(
    instance: Any,
    *,
    daemon: dict[str, Any] | None = None,
    realm: str | None = None,
    workspace: str | None = None,
    roster: Iterable[Any] = (),
    identity_roster: Iterable[Any] | None = None,
    board: dict[str, Any] | None = None,
    turn_budget: dict[str, Any] | None = None,
    capability: dict[str, Any] | None = None,
    installs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the typed situational snapshot for one lane.

    Pure: every input is an already-loaded runtime fact. Both the snapshot
    (`snapshot_prompt_observability`) and the chat caller
    (`_cmd_mission_chat_message`) resolve these and call in, so the widget and
    the model render the same projection.

    ``roster`` is the ADDRESSABLE set — the workspace-scoped list that feeds the
    "On level" advertising block and the mission thread count. ``identity_roster``
    is the FULL, unscoped list used only for identity resolution (who steers
    whom): a steerer in another workspace must still resolve to a name even
    though it is not addressable from here. It defaults to ``roster`` so existing
    callers that pass a single list keep identical behaviour.
    """

    if instance is None:
        return {}
    roster = list(roster or ())
    identity_roster = roster if identity_roster is None else list(identity_roster)
    self_id = optional_text(getattr(instance, "id", None))

    hud: dict[str, Any] = {"preview": True}

    scope = {
        key: value
        for key, value in (("realm", optional_text(realm)), ("workspace", optional_text(workspace)))
        if _clean(value)
    }
    if scope:
        hud["scope"] = scope

    lane = _lane_block(instance)
    if lane:
        hud["lane"] = lane

    mission = _mission_block(instance, roster=roster)
    if mission:
        hud["mission"] = mission

    roster_block = _roster_block(roster, self_id=self_id)

    # S2b (R-IP11): residency, stamped onto the LOCAL roster before it is
    # rendered. An instance that also exists on a paired install gains
    # ``also_on``, so an agent about to address a teammate can see that the same
    # persona is running over there too — the fact that, unseen, produces two
    # briefings sent to what the sender thought was one agent.
    #
    # From the CACHED roster only. The HUD never dials: a prompt block whose
    # assembly depended on a machine that might be asleep would make every turn's
    # opening as slow as the slowest peer.
    install_rows = list(installs or ())
    if roster_block and install_rows:
        _stamp_residency(roster_block, install_rows)
    if roster_block:
        hud["roster"] = roster_block
    if install_rows:
        # Drops when empty, like ``board``: an install with no paired peers
        # contributes NO line, so the fixtures' HUD bytes are untouched and an
        # operator reading a single-machine runtime sees nothing about machines.
        hud["installs"] = install_rows

    # Steering is always emitted (unlike the other blocks, which drop when
    # empty): an explicit empty block is the honest "standalone" answer, and
    # its absence is reserved for HUDs that predate steering entirely. Identity
    # resolution reads the FULL roster — a steerer/steered lane in another
    # workspace is a genuine graph fact even when it is not addressable from
    # here, so scoping must never blank out a steering name.
    hud["steering"] = _steering_block(instance, identity_roster, self_id=self_id)

    # Advisory Mission Board digest (nudge, not instruction): a one-line
    # awareness cue. Absent when there is no board or it has no open cards, so a
    # workspace with no board contributes NO line (nudged-never-forced).
    if isinstance(board, dict) and board:
        hud["board"] = board

    # Wall budget for THIS turn (``turn_budget.TurnWallBudget.hud_block``).
    # Volatile by construction, so it is excluded from the revision hash and
    # fed to the agent through the envelope's always-emitted tail rather than
    # the cached body — it lives on the dict purely so the operator's CONTEXT
    # peek and the observability row see the same number the agent was told.
    if isinstance(turn_budget, dict) and turn_budget:
        hud["turn_budget"] = turn_budget

    # This lane's capability account (``resolve_capability_block``). Volatile by
    # contract for the reasons recorded on its ``HUD_FIELDS`` row, so — exactly
    # like ``turn_budget`` — it is excluded from the revision hash and fed to the
    # agent through the envelope's always-emitted tail rather than the cached
    # body. It lives on the dict so the operator's CONTEXT peek and the
    # observability row see the SAME account the agent was told.
    if isinstance(capability, dict) and capability:
        hud[CAPABILITY_HUD_KEY] = capability

    return hud


def render_situational_hud_block(hud: dict[str, Any]) -> str:
    """Render the fed ``## Runtime Situation`` prompt block from a resolved HUD.

    Kept deliberately compact and read-only in tone: the block is situational
    awareness the operator also sees, not an instruction to act. Returns an empty
    string when there is nothing to say.

    This is the HASHED body, and it renders from :func:`stable_hud_fields` — the
    same derivation :func:`situational_hud_revision` hashes. A field declared
    ``volatile`` in :data:`HUD_FIELDS` is therefore not merely "not rendered
    here by convention": it is not present in the dict this function reads, so
    it CANNOT be rendered here. Volatile facts ride the envelope's
    always-emitted tail instead; putting one behind the revision hash would
    re-snapshot the whole HUD every turn (``turn_budget``) or let a cached body
    show a stale claim (``capability``)."""

    if not isinstance(hud, dict) or not hud:
        return ""
    hud = stable_hud_fields(hud)
    if not hud:
        return ""

    lines: list[str] = [
        "## Runtime Situation",
        "This mirrors the operator's Mission Control runtime HUD so you and the "
        "operator share one view of the runtime. Treat it as read-only context, "
        "not an instruction to act.",
    ]

    scope = section(hud, "scope")
    if scope:
        realm = scope.get("realm") or "no realm"
        workspace = scope.get("workspace") or "no workspace"
        lines.append(f"- Scope: realm {realm} · workspace {workspace}")

    mission = section(hud, "mission")
    if mission:
        bits = [str(mission.get("title") or mission.get("goal_id") or "mission")]
        if _clean(mission.get("state")):
            bits.append(str(mission["state"]))
        if _clean(mission.get("thread_count")):
            count = mission["thread_count"]
            bits.append(f"{count} thread{'' if count == 1 else 's'}")
        lines.append(f"- Mission: {' · '.join(bits)}")
    else:
        lines.append("- Mission: no mission bound to this lane")

    board = section(hud, "board")
    if board:
        segments = [
            (board.get("queued"), "queued"),
            (board.get("active"), "in progress"),
            (board.get("review"), "in review"),
        ]
        parts = [f"{count} {label}" for count, label in segments if isinstance(count, int) and count > 0]
        if parts:
            lines.append(
                f"- Board: {' · '.join(parts)} (a workspace board exists; you MAY add a "
                "card for follow-up work worth tracking — advisory, never required)"
            )

    lane = section(hud, "lane")
    if lane:
        who = lane.get("display_name") or lane.get("persona_instance_id") or "this agent"
        who_bits = [str(who)]
        if _clean(lane.get("persona_instance_id")):
            who_bits.append(f"@{lane['persona_instance_id']}")
        if _clean(lane.get("role")):
            who_bits.append(f"role {lane['role']}")
        lines.append(f"- You: {' · '.join(who_bits)}")

    steering = section(hud, "steering", dict, None)
    if steering is not None:
        steered_by = section(steering, "steered_by", list)
        steers = section(steering, "steers", list)
        if steered_by:
            lines.append(
                "- Steered by: " + ", ".join(_render_handle(e) for e in steered_by if isinstance(e, dict))
            )
        if steers:
            lines.append(
                "- Steers: " + ", ".join(_render_handle(e) for e in steers if isinstance(e, dict))
            )
        if not steered_by and not steers:
            lines.append("- Steering: standalone — no steerer, steers nobody")

    roster = section(hud, "roster", list)
    if roster:
        names = ", ".join(_render_handle(entry) for entry in roster if isinstance(entry, dict))
        lines.append(f"- On level ({len(roster)}): {names}")

    # S2b. After the level, because the level is where this agent works and the
    # other machines are context for it.
    installs = section(hud, "installs", list)
    if installs:
        summary = " · ".join(
            _install_summary(entry) for entry in installs if isinstance(entry, dict)
        )
        lines.append(f"- Installs ({len(installs)}): {summary}")
        for entry in installs:
            if not isinstance(entry, dict):
                continue
            far = [row for row in (entry.get("roster") or ()) if isinstance(row, dict)]
            if not far:
                continue
            # Each handle spelled as the FULL address, the ``_handle`` rule's
            # own reason: a name without the address it answers to is visible
            # and not actionable.
            rendered = ", ".join(
                f"{row.get('persona_id') or row.get('handle')} "
                f"(@{entry.get('ref')}/{row.get('handle')})"
                for row in far
            )
            lines.append(f"  - @{entry.get('ref')}: {rendered}")

    return "\n".join(lines)


def _render_handle(entry: dict[str, Any]) -> str:
    """The shared "Name (@personainst_...)" phrase: the handle IS the address the
    chat/steer verbs accept, so every line naming a teammate carries it — a name
    without its handle is visible but not actionable."""

    name = entry.get("display_name")
    ref = entry.get("persona_instance_id") or entry.get("ref")
    if _clean(name) and _clean(ref) and name != ref:
        rendered = f"{name} (@{ref})"
    elif _clean(ref):
        rendered = f"@{ref}"
    else:
        rendered = str(name or "unknown")
    # R-IP11's residency note, on the line the agent already reads. The age
    # is computed HERE from the cached ``last_turn_at``, never dialled, so
    # this costs the turn nothing.
    notes = [_residency_note(item) for item in section(entry, "also_on", list) if isinstance(item, dict)]
    return f"{rendered} [{'; '.join(notes)}]" if notes else rendered


def _residency_note(item: dict[str, Any]) -> str:
    age = _age_phrase(item.get("last_turn_at"))
    return f"also on @{item.get('ref')}" + (f", last turn there {age} ago" if age and age != "just now" else "")


def _install_summary(entry: dict[str, Any]) -> str:
    """``@mac reachable`` / ``@studio unreachable 12 min`` — one install, one phrase.

    The age is rendered from the stamp at RENDER time rather than stored, so a
    cached HUD body cannot claim a machine went down twelve minutes ago when it
    has been down for two hours.
    """

    ref = entry.get("ref") or entry.get("install_id") or "?"
    word = str(entry.get("reachability") or "unknown")
    since = entry.get("unreachable_since")
    if word == "unreachable" and since:
        age = _age_phrase(since)
        if age:
            return f"@{ref} {word} {age}"
    return f"@{ref} {word}"


def _age_phrase(stamp: Any) -> str:
    """How long ago, in the coarsest useful unit. Empty when unreadable.

    Coarse on purpose: "12 min" is what an operator acts on, and a HUD that said
    "12 min 41 s" would move every turn and defeat the revision hash the stable
    block is delivered under.
    """

    when = parse_iso_utc(stamp)
    if when is None:
        return ""
    seconds = int((datetime.now(timezone.utc) - when).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} d"
