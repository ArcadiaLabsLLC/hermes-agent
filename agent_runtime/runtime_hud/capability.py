"""This lane's capability account — what the cost policy DROPPED, what the envelope REFUSES.

``resolve_capability_block`` (pure: both inputs are already-resolved facts
from their own authorities) and ``render_capability_block``, the volatile
tail's agent-visible lines.
"""

from __future__ import annotations

from typing import Any, Iterable

from agent_runtime.chat_lane_toolsets import DROP_KIND_TOOL, DROP_KIND_TOOLSET
from agent_runtime.permission_modes import permission_mode_is_unbounded
from agent_runtime.terminal_envelope import ENVELOPE_DECISION_LOG

from agent_runtime.runtime_hud.fields import SITUATIONAL_HUD_CAPABILITY_CAP

__layer__ = "policy"


def _capped(names: Iterable[Any]) -> tuple[list[str], int]:
    """Order-preserving dedupe, capped; returns the kept names and the overflow."""

    kept: list[str] = []
    seen: set[str] = set()
    for item in names or ():
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        kept.append(text)
    if len(kept) <= SITUATIONAL_HUD_CAPABILITY_CAP:
        return kept, 0
    return kept[:SITUATIONAL_HUD_CAPABILITY_CAP], len(kept) - SITUATIONAL_HUD_CAPABILITY_CAP


def _names(names: Iterable[Any]) -> str:
    kept, overflow = _capped(names)
    text = ", ".join(kept)
    return f"{text} (+{overflow} more)" if overflow else text


def resolve_capability_block(
    *,
    drops: Iterable[Any] = (),
    envelope: dict[str, Any] | None = None,
    permission_mode: str | None = None,
    permission_source: str | None = None,
) -> dict[str, Any]:
    """Assemble this lane's capability account: what was DROPPED, what is REFUSED.

    Pure, like :func:`resolve_situational_hud`: both inputs are already-resolved
    facts produced by their own authorities, and this module renders them — it
    resolves no policy of its own.

    * ``drops`` — :class:`agent_runtime.chat_lane_toolsets.ChatLaneDrop` values
      from ``persona_runtime.chat_lane_capability_drops`` (G5). Each carries the
      exact root-config key that un-excludes it, which is the whole point of the
      row: the reader can act without reading source.
    * ``envelope`` — the side-effect-free
      ``terminal_envelope.explain_terminal_envelope`` view. Its ``refused`` set
      is split into the operator-grantable classes and the hard floor, because
      telling an agent to ask for a grant that cannot exist would be a new lie
      (the same reasoning that made ``envelope_command_not_grantable`` a
      distinct refusal code).

    * ``permission_mode`` / ``permission_source`` — the posture this turn
      resolved. Since the 2026-08-09 ruling made ``unbounded`` the runtime
      DEFAULT, silence is no longer honest for it: an empty block used to mean
      "nothing was taken away", which a reader could only interpret against an
      assumed bounded baseline. The posture is stated explicitly instead.

    Returns ``{}`` when there is genuinely nothing to account for — a bounded
    lane with no drops and an ungoverned lane refuse nothing, so neither pays a
    line. Honest silence, not a noise block.
    """

    block: dict[str, Any] = {}

    if permission_mode_is_unbounded(permission_mode):
        block["posture"] = {
            "permission_mode": str(permission_mode or "").strip(),
            "permission_source": str(permission_source or "").strip(),
        }

    toolsets: list[str] = []
    tools: list[str] = []
    restorable: list[str] = []
    for drop in drops or ():
        subject = str(getattr(drop, "subject", "") or "").strip()
        if not subject:
            continue
        kind = getattr(drop, "kind", None)
        if kind == DROP_KIND_TOOLSET:
            toolsets.append(subject)
        elif kind == DROP_KIND_TOOL:
            tools.append(subject)
        else:
            continue
        key = str(getattr(drop, "restorable_via", "") or "").strip()
        if key and key not in restorable:
            restorable.append(key)
    if toolsets:
        block["toolsets_dropped"] = toolsets
    if tools:
        block["tools_dropped"] = tools
    if restorable:
        # One persona ⇒ one key in practice; the list shape keeps the block
        # honest if a future dropper ever restores through a different setting.
        block["restorable_via"] = restorable

    if isinstance(envelope, dict) and envelope.get("governed"):
        grantable = {
            str(name) for name in (envelope.get("grantable_command_classes") or ())
        }
        refused = [str(name) for name in (envelope.get("refused") or ())]
        granted = [str(name) for name in (envelope.get("granted") or ())]
        issues = [row for row in (envelope.get("grant_issues") or ()) if isinstance(row, dict)]
        refused_grantable = [name for name in refused if name in grantable]
        refused_hard_floor = [name for name in refused if name not in grantable]
        if granted or refused or issues:
            envelope_block: dict[str, Any] = {
                "lane": str(envelope.get("lane") or "").strip(),
                "role": str(envelope.get("role") or "").strip(),
                "config_key": str(envelope.get("config_key") or "").strip(),
            }
            if granted:
                envelope_block["granted"] = granted
            if refused_grantable:
                envelope_block["refused_grantable"] = refused_grantable
            if refused_hard_floor:
                envelope_block["refused_hard_floor"] = refused_hard_floor
            if issues:
                envelope_block["grant_issues"] = issues
            block["envelope"] = envelope_block

    return block


def render_capability_block(capability: dict[str, Any] | None) -> str:
    """Render the agent-visible capability lines for the volatile envelope tail.

    Two bullets at most, in the same list grammar as
    ``turn_budget.render_turn_budget_line`` and
    ``mcp_admission.render_mcp_admission_line``, because they ride the same tail.

    This is the whole point of the slice: the drops and the envelope refusals
    were already computed and already typed, and the agent still could not SEE
    them — so "I have no terminal" read to the model as an unexplained absence
    and it improvised (the failure class the MCP row was written to retire,
    recurring; see the lane gap audit §6 / G5). Each line therefore states the
    fact, names the ONE authority that could change it, and closes the
    improvisation door explicitly.

    Returns ``""`` for an empty account, so a lane with nothing to report pays
    nothing.
    """

    if not isinstance(capability, dict) or not capability:
        return ""

    lines: list[str] = []

    posture = capability.get("posture") if isinstance(capability.get("posture"), dict) else {}
    if posture:
        mode = str(posture.get("permission_mode") or "").strip()
        source = str(posture.get("permission_source") or "").strip()
        origin = (
            "runtime default"
            if source in ("", "runtime_default")
            else f"source: {source}"
        )
        lines.append(
            f"- No lane restrictions: permission mode '{mode}' ({origin}). Every tool this "
            "runtime registers is on your schema, and the terminal envelope's gated command "
            "classes are granted by this mode rather than by a per-role config grant. Every "
            "such command is RECEIPTED with the mode that allowed it "
            f"({ENVELOPE_DECISION_LOG}) — you are trusted and audited, so act, and keep the "
            "confirmation pause for destructive or irreversible steps."
        )

    toolsets = capability.get("toolsets_dropped") or []
    tools = capability.get("tools_dropped") or []
    if toolsets or tools:
        parts: list[str] = []
        if toolsets:
            parts.append(f"toolset{'' if len(toolsets) == 1 else 's'} {_names(toolsets)}")
        if tools:
            parts.append(f"tool{'' if len(tools) == 1 else 's'} {_names(tools)}")
        keys = capability.get("restorable_via") or []
        restore = (
            f" Only an OPERATOR can restore one, with `{_names(keys)}` in the ROOT "
            "config.yaml."
            if keys
            else ""
        )
        lines.append(
            f"- Dropped on this lane: {' · '.join(parts)}. By design — a per-turn "
            "schema-cost cut applied AFTER role and permission resolution, so it is "
            "NOT a permission problem and no permission mode you can reach restores "
            f"it.{restore} Report the absence plainly; do not hunt for a mode and do "
            "not improvise a workaround."
        )

    envelope = capability.get("envelope") if isinstance(capability.get("envelope"), dict) else {}
    if envelope:
        who = ", ".join(
            part
            for part in (
                f"role {envelope['role']}" if envelope.get("role") else "",
                f"lane {envelope['lane']}" if envelope.get("lane") else "",
            )
            if part
        )
        bits: list[str] = []
        granted = envelope.get("granted") or []
        bits.append(f"granted {_names(granted)}" if granted else "no class granted")
        refused_grantable = envelope.get("refused_grantable") or []
        if refused_grantable:
            key = envelope.get("config_key") or ""
            via = f" — operator-grantable via `{key}`" if key else " — operator-grantable"
            bits.append(f"refused {_names(refused_grantable)}{via}")
        refused_hard_floor = envelope.get("refused_hard_floor") or []
        if refused_hard_floor:
            bits.append(
                f"hard floor no config lifts: {_names(refused_hard_floor)}"
            )
        issues = envelope.get("grant_issues") or []
        if issues:
            bits.append(
                f"{len(issues)} grant-config issue"
                f"{'' if len(issues) == 1 else 's'} — the stanza grants less than it reads"
            )
        lines.append(
            f"- Terminal envelope ({who}): " + "; ".join(bits) + ". A refusal is "
            "final for this turn — relay it to the operator, never retry, reword or "
            "split the command."
        )

    return "\n".join(lines)
