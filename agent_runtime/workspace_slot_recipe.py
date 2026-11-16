"""A slot's READINESS on this machine — the checkout alone — and the credential checks every slot record runs.

Plan ``docs/agent-runtime-harness/planned/slot-setup-recipe-2026-11-15.md`` (owner rulings
2026-11-15/16). The setup recipe lives IN THE REPOSITORY (``.eternia/setup/``, read by
``workspace_slot_repo_recipe.read_recipe``), never in the slot declaration: the declaration's
old ``toolchain.tools`` / ``env_keys`` / ``dotenv`` and ``recipe.steps`` are read nowhere. What is
left here is the one derived step, ``clone`` (its actions Clone and Locate, or Locate alone for a
``repo.local`` slot), and :func:`readiness`.

**Readiness** is THE answer to "ready on this machine" — the probe's report ``status`` is
computed by it too, so there is one authority. **Only the checkout decides Ready**
(``RT-SLOT-READY-IGNORES-TOOLS-AND-KEYS``, owner 2026-11-13; the recipe never gates, decision 4):
ready = bound ∧ the path present ∧ ``checkout: matches``. **An unknown checkout — a clone probe
that answered ``unknown``, or a slot this machine never reported — makes ``ready: "unknown"``,
never ``"yes"``** (the unknowns rule). ``blocking``, ``notes`` and ``orphaned_annotations`` stay
in the answer, for Eternia's Set up until it reads the recipe block.

No credential ever enters a slot record or a recipe: a URL with userinfo, a bearer token or a
secret-shaped assignment is refused by :func:`url_carries_credential` / :func:`text_carries_credential`.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .redaction import BEARER_TOKEN_RE, ENV_SECRET_ASSIGNMENT_RE, SECRET_ASSIGNMENT_RE

__layer__ = "policy"

# ── vocabulary ───────────────────────────────────────────────────────────────

STEP_CLONE = "clone"
#: The clone step's id.
CLONE_STEP_ID = "clone"

READY_YES = "yes"
READY_NO = "no"
READY_UNKNOWN = "unknown"

STATE_DONE = "done"
STATE_TODO = "todo"
STATE_WARNING = "warning"
STATE_UNKNOWN = "unknown"

CHECKLIST_NOT_CLONED = "not_cloned"
CHECKLIST_PATH_MISSING = "path_missing"
CHECKLIST_REMOTE_MISMATCH = "remote_mismatch"
CHECKLIST_NEEDS_SETUP = "needs_setup"
CHECKLIST_READY = "ready"
CHECKLIST_UNKNOWN = "unknown"

UNKNOWN_NOT_REPORTED = "not_reported"
UNKNOWN_PROBE_ABSENT = "probe_absent"
UNKNOWN_PROBE_UNKNOWN = "probe_unknown"


# ── credentials never enter a record ─────────────────────────────────────────


def url_carries_credential(url: str) -> bool:
    """True when ``url`` names userinfo a credential could hide in.

    ``https://token@host`` and ``https://user:pass@host`` are refused (a token rides as the
    user just as often as the password); ssh may name a USER (``ssh://git@host``, the scp form
    ``git@host:path``) but never a password.
    """

    text = str(url or "").strip()
    if "://" not in text:
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return True
    if parts.scheme.lower() in ("http", "https"):
        return bool(parts.username or parts.password or "@" in parts.netloc)
    return parts.password is not None


def text_carries_credential(text: str) -> bool:
    """A credential-shaped token: a URL with userinfo, a bearer token, a secret assignment."""

    value = str(text or "")
    if BEARER_TOKEN_RE.search(value) or SECRET_ASSIGNMENT_RE.search(value) or ENV_SECRET_ASSIGNMENT_RE.search(value):
        return True
    return any(url_carries_credential(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://\S+", value))


# ── the clone step ───────────────────────────────────────────────────────────


def clone_step(slot_name: str, slot: dict[str, Any]) -> dict[str, Any]:
    """The slot's one derived step: Clone or Locate (Locate alone for a ``repo.local`` slot)."""

    repo = slot.get("repo") or {}
    # A local slot has no clone URL (``clone_slot`` refuses it): Locate is its one meaningful action
    # (RT-PROJECT-LOCAL-FOLDER-READINESS).
    local = repo.get("local") is True
    return {
        "id": CLONE_STEP_ID, "kind": STEP_CLONE, "slot": slot_name, "derived": True,
        "label": f"Locate {slot_name}" if local else f"Clone or locate {slot_name}", "clone_url": repo.get("clone_url"),
        "default_branch": repo.get("default_branch"), "actions": ["locate"] if local else ["clone", "locate"],
    }


# ── readiness: the one answer to "ready on this machine" ─────────────────────


#: ``checkout`` probe → the clone step's ``(state, why)``; any other value is an unknown probe.
_CHECKOUT_STATES = {
    "matches": (STATE_DONE, None),
    "local": (STATE_DONE, None),
    "folder": (STATE_DONE, None),
    "remote_mismatch": (STATE_WARNING, "remote_mismatch"),
    "not_a_repo": (STATE_TODO, "not_a_repo"),
    None: (STATE_UNKNOWN, UNKNOWN_PROBE_ABSENT),
}

# The clone step's state -> (ready, checklist row); any other state is a ready checkout.
_CLONE_READINESS = {
    STATE_UNKNOWN: (READY_UNKNOWN, CHECKLIST_UNKNOWN),
    STATE_WARNING: (READY_NO, CHECKLIST_REMOTE_MISMATCH),
    STATE_TODO: (READY_NO, CHECKLIST_NEEDS_SETUP),
}


def _clone_answer(row: dict[str, Any] | None) -> tuple[str, str | None, str, str]:
    """``(state, why, ready, checklist)`` of the clone step against this machine's report row."""

    if row is None:
        return STATE_UNKNOWN, UNKNOWN_NOT_REPORTED, READY_UNKNOWN, CHECKLIST_UNKNOWN
    if not row.get("bound"):
        return STATE_TODO, None, READY_NO, CHECKLIST_NOT_CLONED
    if row.get("status") == "path_missing":
        return STATE_TODO, None, READY_NO, CHECKLIST_PATH_MISSING
    state, why = _CHECKOUT_STATES.get(row.get("checkout"), (STATE_UNKNOWN, UNKNOWN_PROBE_UNKNOWN))
    ready, checklist = _CLONE_READINESS.get(state, (READY_YES, CHECKLIST_READY))
    return state, why, ready, checklist


def readiness(slot_name: str, slot: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    """This machine's checklist for one slot: ``ready``, the checklist row, and the clone step's state.

    ``row`` is this machine's report row for the slot (``machines.<me>.slots.<slot>``), or None
    when this machine never reported it. Ready is the checkout alone: nothing a recipe lists is read.
    """

    state, why, ready, checklist = _clone_answer(row)
    step = {**clone_step(slot_name, slot), "state": state, "why": why}
    return {
        "ready": ready,
        "checklist": checklist,
        "steps": [step],
        "blocking": [CLONE_STEP_ID] if state in (STATE_TODO, STATE_WARNING) else [],
        "unknown": [CLONE_STEP_ID] if state == STATE_UNKNOWN else [],
        "notes": [],
        "orphaned_annotations": [],
    }


__all__ = [
    "CLONE_STEP_ID",
    "READY_NO",
    "READY_UNKNOWN",
    "READY_YES",
    "clone_step",
    "readiness",
    "text_carries_credential",
    "url_carries_credential",
]
