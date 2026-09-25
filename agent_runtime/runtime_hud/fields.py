"""Which lane a HUD key rides — the ONE declaration, and what derives from it.

VOCABULARY/TABLE module (sheet ``runtime_hud.md`` §1): ``HudField`` /
``HUD_FIELDS`` declare every HUD key and whether it is volatile;
``stable_hud_fields`` is the single derivation point of the body/tail split, and
``situational_hud_revision`` hashes what it keeps. Also the two list caps.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

__layer__ = "models"


# Bound the roster so a large level cannot bloat every chat turn. The operator's
# widget wraps chips; the fed block lists names and notes the overflow count.
SITUATIONAL_HUD_ROSTER_CAP = 16

# Bound each capability list for the same reason the roster is bounded: the
# capability block rides EVERY turn, so a policy that later widens the excluded
# toolset set — or a command-class taxonomy that grows past seven — must not
# silently turn two lines into a wall. Overflow is counted, never dropped
# without saying so.
SITUATIONAL_HUD_CAPABILITY_CAP = 8


# HUD key for this lane's capability account — what the chat-lane cost policy
# removed from this turn, and what the terminal safety envelope will refuse.
CAPABILITY_HUD_KEY = "capability"


@dataclass(frozen=True, slots=True)
class HudField:
    """One HUD key, and the ONE declaration of which delivery lane it rides.

    ``volatile`` is stated here and nowhere else. Both consumers of the
    body/tail split derive from it — :func:`situational_hud_revision` excludes
    volatile fields from the hash, and :func:`render_situational_hud_block`
    renders from :func:`stable_hud_fields` — so a volatile fact CANNOT reach the
    hashed body even if a later edit tries to render it there. The predecessor
    convention (a ``_VOLATILE_HUD_KEYS`` frozenset, plus a hand-written promise
    in the body renderer's docstring that it would never touch those keys) put
    the declaration in one place and the enforcement in none.
    """

    key: str
    volatile: bool
    summary: str = ""


#: The declared HUD field roster. Adding a key to the HUD means adding a row
#: here; ``tests/agent_runtime/test_runtime_hud_field_contract.py`` fails a HUD
#: that emits an undeclared key, so the roster cannot silently fall behind.
#:
#: The two volatile rows are volatile for two INDEPENDENT reasons that end at
#: the same contract:
#:
#: * ``turn_budget`` changes on every single turn by construction (a wall-clock
#:   countdown), so hashing it would force a full re-snapshot of the whole stable
#:   HUD block every turn and defeat the snapshot/unchanged delivery contract.
#: * ``capability`` is mostly stable but must be true on EVERY turn regardless of
#:   delivery. A cached ``unchanged`` stub — and, worse, an ``unavailable``
#:   delivery, which drops the body entirely — would leave an agent believing it
#:   still has a capability this turn dropped, or leave a refusal unexplained.
#:   Same reasoning, and the same lane, as the MCP admission line
#:   (``mcp_admission.render_mcp_admission_line``): a capability claim that can go
#:   stale in a cache is worse than no claim at all.
HUD_FIELDS: tuple[HudField, ...] = (
    HudField("preview", volatile=False, summary="marks the dict as the fed HUD projection"),
    HudField("scope", volatile=False, summary="realm · workspace"),
    HudField("lane", volatile=False, summary="this agent's identity/role/mode"),
    HudField("mission", volatile=False, summary="bound goal, state, thread count"),
    HudField("roster", volatile=False, summary="addressable on-level agents"),
    HudField("steering", volatile=False, summary="who steers this lane, and whom it steers"),
    HudField("board", volatile=False, summary="advisory Mission Board digest"),
    # S2b / R-IP11. STABLE, not volatile, and that is a claim about the data
    # rather than a convenience: every fact in it is read from this install's own
    # two peer files, which change when a ceremony or a push edge changes them
    # and not once per turn. Hashing it is therefore cheap and correct — an
    # agent whose paired installs did not move gets the cached body, and one
    # whose peer just went unreachable gets a fresh one. (``turn_budget`` is
    # volatile because it moves every turn by construction; this does not.)
    HudField("installs", volatile=False, summary="paired installs, cached rosters, residency"),
    HudField("turn_budget", volatile=True, summary="wall-clock window left on THIS turn"),
    HudField(
        CAPABILITY_HUD_KEY,
        volatile=True,
        summary="capability drops + terminal-envelope grants/refusals for THIS turn",
    ),
)

_HUD_FIELD_BY_KEY: dict[str, HudField] = {field.key: field for field in HUD_FIELDS}


def hud_field(key: str) -> HudField | None:
    """The declaration for one HUD key, or ``None`` when it is undeclared."""

    return _HUD_FIELD_BY_KEY.get(str(key))


def is_volatile_hud_key(key: str) -> bool:
    """Whether a key rides the always-emitted tail instead of the hashed body.

    An UNDECLARED key is treated as stable. That direction is the safe one: an
    undeclared key stays in the hash, so the worst case is an extra re-snapshot.
    Defaulting the other way would silently drop a new fact out of the revision
    and let a cached body go stale — the exact failure the split exists to
    prevent.
    """

    field = _HUD_FIELD_BY_KEY.get(str(key))
    return bool(field and field.volatile)


def volatile_hud_keys() -> frozenset[str]:
    """The declared volatile key set (derived, never a second hand-kept list)."""

    return frozenset(field.key for field in HUD_FIELDS if field.volatile)


def stable_hud_fields(hud: dict[str, Any] | None) -> dict[str, Any]:
    """``hud`` with every declared-volatile field removed.

    THE single derivation point of the body/tail split. Both the revision hash
    and the body renderer read this, so "volatile" is decided once, in
    :data:`HUD_FIELDS`, and enforced structurally in both places.
    """

    if not isinstance(hud, dict):
        return {}
    return {key: value for key, value in hud.items() if not is_volatile_hud_key(key)}


def situational_hud_revision(hud: dict[str, Any] | None) -> str:
    """Return a stable revision for the exact runtime snapshot fed this turn.

    Fields declared ``volatile`` in :data:`HUD_FIELDS` are excluded: the revision
    describes the STABLE picture, so a per-turn countdown never invalidates it.
    """

    if not isinstance(hud, dict) or not hud:
        return "hud_unavailable"
    stable = stable_hud_fields(hud)
    if not stable:
        return "hud_unavailable"
    canonical = json.dumps(
        stable,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8", errors="replace")
    return "hud_" + hashlib.sha256(canonical).hexdigest()[:16]
