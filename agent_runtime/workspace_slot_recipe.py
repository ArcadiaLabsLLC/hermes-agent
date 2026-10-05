"""The setup recipe ("image") — the slot declaration READ AS A CHECKLIST (build plan §3.5, Phase B).

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §3.5 and §11
(OWNER calls 8a, 8d). The recipe is not a second model. It is two things:

* **Derived steps**, materialised from the declaration every time it is read — never stored,
  so the owner cannot delete one, only ANNOTATE it (``hint`` text, an http(s) ``url``):
  ``clone`` (one per slot; its actions are Clone and Locate), ``tool:<name>`` per declared
  tool, ``env_key:<KEY>`` per declared env key, ``dotenv`` when the slot declares a ``.env``.
* **Owner steps** — ``command`` steps the publish right adds (``argv``, ``cwd_slot``,
  ``run: on_setup_click | never_auto``). A command NEVER runs automatically (call 8d): it runs
  only on an explicit ``runtime.workspace.recipe.run_step``; ``run`` says whether the Set up
  flow OFFERS it (``on_setup_click``) or lists it for a manual run only (``never_auto``).

``slot.recipe.steps`` stores ONLY the owner's part, in the owner's order: annotations
(``{id, hint?, url?}`` keyed by a derived id) and command steps. An annotation whose derived
step left the declaration is kept and reported ``orphaned``, never applied.

**Readiness** (:func:`readiness`) is THE answer to "ready on this machine" — the probe's
report ``status`` is computed by it too, so there is one authority:
ready = bound ∧ ``checkout: matches`` ∧ every declared tool ``set`` (and at least its
``min_version`` when one is declared) ∧ every REQUIRED env key ``set`` ∧ (a ``.env`` declared ⇒
the file present ∧ every required key ``set``). Optional keys missing are NOTES. **Any unknown
input — a probe that answered ``unknown``, or a probe the report does not carry at all — makes
``ready: "unknown"``, never ``"yes"``** (the unknowns rule; it outranks a definite ``"no"``,
as the probe's own status always has).

No credential ever enters a recipe: a command whose argv or label, or an annotation whose hint
or url, carries a URL with userinfo, a bearer token or a secret-shaped assignment is refused
``credential_in_step``.

**One validator, two callers.** ``recipe.set`` (:func:`normalize_owner_steps`) refuses the whole
edit on the first bad step; the realm pull (``workspace_slots_sync``) reads a PEER's stored steps
through the same :func:`normalize_owner_step` with ``held=True`` and drops only the bad step. A
held step is a record read back, so the drift a later re-declaration legitimately leaves is not a
refusal there — an annotation orphaned by its derived step (``materialize`` reports it) and a
``cwd_slot`` the document holds only as a tombstone (``run_step`` re-checks liveness) — while a
field a stored step never carries is (a conforming writer stores only what this module returns).
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from .redaction import BEARER_TOKEN_RE, ENV_SECRET_ASSIGNMENT_RE, SECRET_ASSIGNMENT_RE

__layer__ = "policy"

# ── vocabulary ───────────────────────────────────────────────────────────────

STEP_CLONE = "clone"
STEP_TOOL = "tool"
STEP_ENV_KEY = "env_key"
STEP_DOTENV = "dotenv"
STEP_COMMAND = "command"
DERIVED_KINDS = (STEP_CLONE, STEP_TOOL, STEP_ENV_KEY, STEP_DOTENV)

RUN_ON_SETUP_CLICK = "on_setup_click"
RUN_NEVER_AUTO = "never_auto"
RUN_MODES = (RUN_ON_SETUP_CLICK, RUN_NEVER_AUTO)

#: Derived-step ids that are not ``<kind>:<name>``.
CLONE_STEP_ID = "clone"
DOTENV_STEP_ID = "dotenv"
#: A command id: never a colon (so never a derived id) and never a reserved word.
_COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RESERVED_IDS = frozenset({CLONE_STEP_ID, DOTENV_STEP_ID})
#: The shape of a derived-step id — what a HELD annotation orphaned by a re-declaration still has.
_DERIVED_ID_RE = re.compile(r"^(?:clone|dotenv|(?:tool|env_key):[^\s:]{1,80})$")
#: The only fields an annotation may carry.
ANNOTATION_FIELDS = frozenset({"id", "kind", "hint", "url"})

READY_YES = "yes"
READY_NO = "no"
READY_UNKNOWN = "unknown"

STATE_DONE = "done"
STATE_TODO = "todo"
STATE_WARNING = "warning"
STATE_UNKNOWN = "unknown"
STATE_OPTIONAL_MISSING = "optional_missing"
#: A derived step behind an unbound slot: nothing is probed until the checkout exists.
STATE_PENDING = "pending"
STATE_OFFERED = "offered"
STATE_MANUAL = "manual"

CHECKLIST_NOT_CLONED = "not_cloned"
CHECKLIST_PATH_MISSING = "path_missing"
CHECKLIST_REMOTE_MISMATCH = "remote_mismatch"
CHECKLIST_NEEDS_SETUP = "needs_setup"
CHECKLIST_READY = "ready"
CHECKLIST_UNKNOWN = "unknown"

UNKNOWN_NOT_REPORTED = "not_reported"
UNKNOWN_PROBE_ABSENT = "probe_absent"
UNKNOWN_PROBE_UNKNOWN = "probe_unknown"
UNKNOWN_VERSION_UNREADABLE = "version_unreadable"

REASON_UNKNOWN_STEP = "unknown_step"
REASON_DERIVED_STEP_IMMUTABLE = "derived_step_immutable"
REASON_INVALID_STEP = "invalid_step"
REASON_DUPLICATE_STEP_ID = "duplicate_step_id"
REASON_CREDENTIAL_IN_STEP = "credential_in_step"

_VERSION_RE = re.compile(r"^[0-9]{1,9}(?:\.[0-9]{1,9})*$")


class RecipeRefused(ValueError):
    """An owner step list this policy will not hold; ``reason`` is the wire word."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


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


# ── derived steps ────────────────────────────────────────────────────────────


def tool_step_id(name: str) -> str:
    return f"{STEP_TOOL}:{name}"


def env_key_step_id(key: str) -> str:
    return f"{STEP_ENV_KEY}:{key}"


def derived_steps(slot_name: str, slot: dict[str, Any]) -> list[dict[str, Any]]:
    """The declaration as checklist steps, in order: clone, tools, env keys, ``.env``."""

    repo = slot.get("repo") or {}
    toolchain = slot.get("toolchain") or {}
    steps: list[dict[str, Any]] = [{
        "id": CLONE_STEP_ID, "kind": STEP_CLONE, "slot": slot_name, "derived": True,
        "label": f"Clone or locate {slot_name}", "clone_url": repo.get("clone_url"),
        "default_branch": repo.get("default_branch"), "actions": ["clone", "locate"],
    }]
    for tool in toolchain.get("tools") or []:
        steps.append({"id": tool_step_id(tool["name"]), "kind": STEP_TOOL, "slot": slot_name, "derived": True,
                      "label": f"Install {tool['name']}", "tool": tool["name"], "min_version": tool.get("min_version")})
    for row in toolchain.get("env_keys") or []:
        steps.append({"id": env_key_step_id(row["key"]), "kind": STEP_ENV_KEY, "slot": slot_name, "derived": True,
                      "label": f"Set {row['key']}", "key": row["key"], "required": bool(row.get("required")),
                      "secret": bool(row.get("secret"))})
    dotenv = toolchain.get("dotenv")
    if dotenv:
        keys = [{"key": r["key"], "required": bool(r.get("required")), "secret": bool(r.get("secret"))}
                for r in dotenv.get("keys") or []]
        steps.append({"id": DOTENV_STEP_ID, "kind": STEP_DOTENV, "slot": slot_name, "derived": True,
                      "label": f"Create {dotenv.get('path') or '.env'}", "path": dotenv.get("path") or ".env",
                      "keys": keys})
    return steps


# ── the owner's part ─────────────────────────────────────────────────────────


#: The only fields a STORED command step carries (what :func:`_command` returns).
COMMAND_FIELDS = frozenset({"id", "kind", "label", "argv", "cwd_slot", "run"})


def _annotation(entry: dict[str, Any], derived: dict[str, dict[str, Any]], *, held: bool) -> dict[str, Any]:
    step_id = str(entry.get("id") or "")
    target = derived.get(step_id)
    if target is None and not (held and _DERIVED_ID_RE.match(step_id)):
        raise RecipeRefused(REASON_UNKNOWN_STEP, "not a derived step of this slot")
    extra = sorted(set(entry) - ANNOTATION_FIELDS)
    if extra or (target is not None and entry.get("kind") not in (None, target["kind"])):
        raise RecipeRefused(REASON_DERIVED_STEP_IMMUTABLE,
                            f"{step_id}: a derived step is annotated (hint, url), never edited ({extra or entry.get('kind')})")
    url = entry.get("url")
    if url is not None and not re.match(r"^https?://\S+$", str(url)):
        raise RecipeRefused(REASON_INVALID_STEP, f"{step_id}: an annotation url is http(s)")
    if url is not None and url_carries_credential(str(url)):
        raise RecipeRefused(REASON_CREDENTIAL_IN_STEP, f"{step_id}: the url carries userinfo")
    if entry.get("hint") is not None and text_carries_credential(str(entry["hint"])):
        raise RecipeRefused(REASON_CREDENTIAL_IN_STEP, f"{step_id}: the hint is credential-shaped")
    out = {"id": step_id}
    if entry.get("hint") is not None:
        out["hint"] = str(entry["hint"])
    if url is not None:
        out["url"] = str(url)
    return out


def _command(entry: dict[str, Any], slot_name: str, names: frozenset[str], *, held: bool) -> dict[str, Any]:
    step_id = str(entry.get("id") or "")
    if not _COMMAND_ID_RE.match(step_id) or step_id in _RESERVED_IDS:
        raise RecipeRefused(REASON_INVALID_STEP, "a command id is [A-Za-z0-9_-]{1,64}, not a reserved id")
    extra = sorted(set(entry) - COMMAND_FIELDS)
    if held and extra:
        reason = REASON_CREDENTIAL_IN_STEP if any(
            text_carries_credential(f"{key}={json.dumps(entry[key], default=str)}") for key in extra) else REASON_INVALID_STEP
        raise RecipeRefused(reason, f"{step_id}: a stored command carries no {extra}")
    argv = entry.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        raise RecipeRefused(REASON_INVALID_STEP, f"{step_id}: argv is a non-empty list of strings")
    if any(text_carries_credential(a) for a in argv):
        raise RecipeRefused(REASON_CREDENTIAL_IN_STEP, f"{step_id}: an argv token is credential-shaped")
    if entry.get("label") is not None and text_carries_credential(str(entry["label"])):
        raise RecipeRefused(REASON_CREDENTIAL_IN_STEP, f"{step_id}: the label is credential-shaped")
    run = entry.get("run") or RUN_ON_SETUP_CLICK
    if run not in RUN_MODES:
        raise RecipeRefused(REASON_INVALID_STEP, f"{step_id}: run is one of {RUN_MODES}")
    cwd_slot = str(entry.get("cwd_slot") or slot_name)
    if cwd_slot not in names:
        raise RecipeRefused(REASON_INVALID_STEP, f"{step_id}: cwd_slot {cwd_slot!r} is not a declared slot")
    return {"id": step_id, "kind": STEP_COMMAND, "label": str(entry.get("label") or " ".join(argv)),
            "argv": list(argv), "cwd_slot": cwd_slot, "run": run}


def normalize_owner_step(entry: Any, slot_name: str, derived: dict[str, dict[str, Any]],
                         names: Iterable[str], *, held: bool = False) -> dict[str, Any]:
    """ONE owner step as stored, or :class:`RecipeRefused` — the validator both callers share.

    ``derived`` is the slot's derived steps by id. ``names`` are the slots a command's
    ``cwd_slot`` may name: the LIVE ones for an edit, every name the document holds (tombstones
    too) for a ``held`` record read back from a peer.
    """

    if not isinstance(entry, dict):
        raise RecipeRefused(REASON_INVALID_STEP, "every step is an object")
    is_command = entry.get("kind") == STEP_COMMAND
    if not is_command and entry.get("kind") not in (None, *DERIVED_KINDS):
        raise RecipeRefused(REASON_INVALID_STEP, "an owner step is a command or an annotation of a derived kind")
    if is_command:
        return _command(entry, slot_name, frozenset(names), held=held)
    return _annotation(entry, derived, held=held)


def derived_by_id(slot_name: str, slot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["id"]: step for step in derived_steps(slot_name, slot)}


def normalize_owner_steps(slot_name: str, slot: dict[str, Any], steps: Any,
                          live_names: Iterable[str]) -> list[dict[str, Any]]:
    """The owner's step list as stored, or :class:`RecipeRefused`.

    A derived step cannot be deleted (it is never stored, so omitting it changes nothing) and
    cannot be edited — only annotated; the owner ADDS ``command`` steps.
    """

    if not isinstance(steps, list):
        raise RecipeRefused(REASON_INVALID_STEP, "steps must be a list")
    derived = derived_by_id(slot_name, slot)
    names = frozenset(live_names)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in steps:
        step = normalize_owner_step(entry, slot_name, derived, names)
        if step["id"] in seen:
            raise RecipeRefused(REASON_DUPLICATE_STEP_ID, step["id"])
        seen.add(step["id"])
        out.append(step)
    return out


def materialize(slot_name: str, slot: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """``(steps, orphaned)``: derived steps (annotated) then the owner's commands, in order.

    ``orphaned`` names annotations whose derived step the declaration no longer has.
    """

    stored = list(((slot.get("recipe") or {}).get("steps")) or [])
    derived = derived_steps(slot_name, slot)
    by_id = {step["id"]: step for step in derived}
    orphaned = []
    commands = []
    for entry in stored:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == STEP_COMMAND:
            commands.append({**entry, "derived": False, "slot": slot_name})
        elif entry.get("id") in by_id:
            by_id[entry["id"]].update({k: v for k, v in entry.items() if k in ("hint", "url")})
        else:
            orphaned.append(str(entry.get("id")))
    return derived + commands, orphaned


# ── readiness: the one answer to "ready on this machine" ─────────────────────


def _probe_state(value: Any, *, required: bool = True) -> tuple[str, str | None]:
    if value is None:
        return STATE_UNKNOWN, UNKNOWN_PROBE_ABSENT
    if value == "set":
        return STATE_DONE, None
    if value == "missing":
        return (STATE_TODO if required else STATE_OPTIONAL_MISSING), None
    return STATE_UNKNOWN, UNKNOWN_PROBE_UNKNOWN


def _tool_state(step: dict[str, Any], row: dict[str, Any]) -> tuple[str, str | None]:
    probe = (row.get("tools") or {}).get(step["tool"])
    state, why = _probe_state((probe or {}).get("status") if probe is not None else None)
    minimum = step.get("min_version")
    if state != STATE_DONE or not minimum:
        return state, why
    found = (probe or {}).get("version")
    if not found or not _VERSION_RE.match(str(found)) or not _VERSION_RE.match(str(minimum)):
        return STATE_UNKNOWN, UNKNOWN_VERSION_UNREADABLE
    from hermes_platform.resolver.availability import version_at_least

    return (STATE_DONE, None) if version_at_least(str(found), str(minimum)) else (STATE_TODO, "version_too_old")


def _dotenv_state(step: dict[str, Any], row: dict[str, Any]) -> tuple[str, str | None]:
    probe = row.get("dotenv")
    if probe is None:
        return STATE_UNKNOWN, UNKNOWN_PROBE_ABSENT
    keys = probe.get("keys") or {}
    states = [_probe_state(keys.get(k["key"]), required=k["required"]) for k in step["keys"]]
    if not probe.get("present") and any(k["required"] for k in step["keys"]):
        states.append((STATE_TODO, None))
    for wanted in (STATE_UNKNOWN, STATE_TODO, STATE_OPTIONAL_MISSING):
        hit = next((s for s in states if s[0] == wanted), None)
        if hit:
            return hit
    return STATE_DONE, None


#: ``checkout`` probe → the clone step's ``(state, why)``; any other value is an unknown probe.
_CHECKOUT_STATES = {
    "matches": (STATE_DONE, None),
    "remote_mismatch": (STATE_WARNING, "remote_mismatch"),
    "not_a_repo": (STATE_TODO, "not_a_repo"),
    None: (STATE_UNKNOWN, UNKNOWN_PROBE_ABSENT),
}


def _clone_state(_step: dict[str, Any], row: dict[str, Any]) -> tuple[str, str | None]:
    return _CHECKOUT_STATES.get(row.get("checkout"), (STATE_UNKNOWN, UNKNOWN_PROBE_UNKNOWN))


def _env_key_state(step: dict[str, Any], row: dict[str, Any]) -> tuple[str, str | None]:
    return _probe_state((row.get("env_keys") or {}).get(step["key"]), required=step["required"])


def _command_state(step: dict[str, Any], _row: dict[str, Any]) -> tuple[str, str | None]:
    return (STATE_OFFERED if step.get("run") == RUN_ON_SETUP_CLICK else STATE_MANUAL), None


#: Step kind → how its state is read from this machine's report row.
_STEP_STATES = {
    STEP_CLONE: _clone_state,
    STEP_TOOL: _tool_state,
    STEP_ENV_KEY: _env_key_state,
    STEP_DOTENV: _dotenv_state,
    STEP_COMMAND: _command_state,
}


def step_state(step: dict[str, Any], row: dict[str, Any]) -> tuple[str, str | None]:
    """``(state, why)`` of one step against this machine's report row (bound rows only)."""

    return _STEP_STATES[step["kind"]](step, row)


def readiness(slot_name: str, slot: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    """This machine's checklist for one slot: ``ready``, the checklist row, and every step's state.

    ``row`` is this machine's report row for the slot (``machines.<me>.slots.<slot>``), or None
    when this machine never reported it.
    """

    steps, orphaned = materialize(slot_name, slot)
    states: dict[str, dict[str, Any]] = {}
    if row is None or not row.get("bound") or row.get("status") == "path_missing":
        for step in steps:
            if step["kind"] == STEP_COMMAND:
                state, why = step_state(step, {})
            elif row is None:
                state, why = STATE_UNKNOWN, UNKNOWN_NOT_REPORTED
            else:
                state, why = (STATE_TODO, None) if step["kind"] == STEP_CLONE else (STATE_PENDING, "not_bound")
            states[step["id"]] = {"state": state, "why": why}
        if row is None:
            ready, checklist = READY_UNKNOWN, CHECKLIST_UNKNOWN
        else:
            ready = READY_NO
            checklist = CHECKLIST_NOT_CLONED if not row.get("bound") else CHECKLIST_PATH_MISSING
        return _answer(steps, orphaned, states, ready, checklist)
    for step in steps:
        state, why = step_state(step, row)
        states[step["id"]] = {"state": state, "why": why}
    derived_states = [states[s["id"]]["state"] for s in steps if s.get("derived")]
    if STATE_UNKNOWN in derived_states:
        ready, checklist = READY_UNKNOWN, CHECKLIST_UNKNOWN
    elif states[CLONE_STEP_ID]["state"] == STATE_WARNING:
        ready, checklist = READY_NO, CHECKLIST_REMOTE_MISMATCH
    elif STATE_TODO in derived_states:
        ready, checklist = READY_NO, CHECKLIST_NEEDS_SETUP
    else:
        ready, checklist = READY_YES, CHECKLIST_READY
    return _answer(steps, orphaned, states, ready, checklist)


def _answer(steps, orphaned, states, ready, checklist) -> dict[str, Any]:
    def ids(state: str) -> list[str]:
        return [s["id"] for s in steps if s.get("derived") and states[s["id"]]["state"] == state]

    return {
        "ready": ready,
        "checklist": checklist,
        "steps": [{**step, **states[step["id"]]} for step in steps],
        "blocking": ids(STATE_TODO) + ids(STATE_WARNING),
        "unknown": ids(STATE_UNKNOWN),
        "notes": ids(STATE_OPTIONAL_MISSING),
        "orphaned_annotations": orphaned,
    }


__all__ = [
    "DERIVED_KINDS",
    "READY_NO",
    "READY_UNKNOWN",
    "READY_YES",
    "RUN_MODES",
    "RecipeRefused",
    "derived_steps",
    "derived_by_id",
    "materialize",
    "normalize_owner_step",
    "normalize_owner_steps",
    "readiness",
    "step_state",
    "text_carries_credential",
    "url_carries_credential",
]
