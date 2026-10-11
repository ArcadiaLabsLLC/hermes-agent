"""This machine's private fill for each repo slot: tool paths, env values, PATH head, ``.env``, venv.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §3.2. The PATH
half of a slot's fill is the machine-root registry (``machine_roots.json`` ``roots.<slot>``);
THIS file is the environment half, ``machine_slot_env.json`` v1, beside it in the hermes
root because it describes the MACHINE, not one profile::

    {"schema_version": 1, "workspaces": {"ws_…": {"launcher": {
        "tool_paths": {"flutter": "C:\\\\flutter\\\\bin\\\\flutter.bat"}, "env": {"FLUTTER_ROOT": "C:\\\\flutter"},
        "path_prepend": ["C:\\\\flutter\\\\bin"], "dotenv": ".env", "venv": null, "bound_at": "…"}}}}

**Private, never synced, but accounted for.** The filename is hard-excluded from realm sync
exactly like ``auth.json`` and ``machine_roots.json``; what other machines see is the
slot document's ``machines.<id>`` ACCOUNTING (set / missing / unknown per key), never a
value. Plain values live here because this is the machine's own file — written ``0600`` —
and a key the slot declaration marks ``secret`` is REFUSED here (``secret_in_env``): it
belongs in the slot's ``.env`` under the bound path, read by the process that needs it,
never copied.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_constants import get_default_hermes_root
from utils import atomic_json_write

from .json_document import read_versioned_document

__layer__ = "stores"

MACHINE_SLOT_ENV_FILENAME = "machine_slot_env.json"
SLOT_ENV_SCHEMA_VERSION = 1
REASON_SECRET_IN_ENV = "secret_in_env"
REASON_INVALID_FILL = "invalid_fill"


class SlotEnvRefused(ValueError):
    """A fill this file will not hold; ``reason`` is the wire word."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class SlotFill:
    """One slot's environment on THIS machine."""

    tool_paths: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    path_prepend: tuple[str, ...] = ()
    dotenv: str | None = None
    venv: str | None = None
    bound_at: str = ""


def slot_env_path() -> Path:
    return Path(get_default_hermes_root()) / MACHINE_SLOT_ENV_FILENAME


def _read() -> dict[str, Any]:
    return read_versioned_document(slot_env_path(), schema_version=SLOT_ENV_SCHEMA_VERSION, collection="workspaces")


def slot_fill(workspace_id: str, slot: str) -> SlotFill | None:
    """This machine's fill for ``slot`` in ``workspace_id``, or None when none was set."""

    entry = (_read()["workspaces"].get(workspace_id) or {}).get(slot)
    if not isinstance(entry, dict):
        return None
    return SlotFill(
        tool_paths={str(k): str(v) for k, v in (entry.get("tool_paths") or {}).items()},
        env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
        path_prepend=tuple(str(item) for item in entry.get("path_prepend") or ()),
        dotenv=entry.get("dotenv") or None,
        venv=entry.get("venv") or None,
        bound_at=str(entry.get("bound_at") or ""),
    )


def fill_shape(workspace_id: str, slot: str) -> dict[str, Any] | None:
    """The fill's NON-SECRET shape for ``slots.show``: env key NAMES, tool paths, PATH head,
    ``.env``, venv — never an env VALUE. None when this machine set no fill for the slot.

    It is what an editor needs to change one key without clearing the rest: every field but
    the env values round-trips as-is, and the values it cannot see are kept by NAME
    (``set_slot_fill(env_keep=…)``).
    """

    fill = slot_fill(workspace_id, slot)
    if fill is None:
        return None
    return {
        "env_keys": sorted(fill.env),
        "tool_paths": dict(sorted(fill.tool_paths.items())),
        "path_prepend": list(fill.path_prepend),
        "dotenv": fill.dotenv,
        "venv": fill.venv,
        "bound_at": fill.bound_at,
    }


def _string_map(value: Any, name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise SlotEnvRefused(REASON_INVALID_FILL, f"{name} must map strings to strings")
    return dict(value)


def set_slot_fill(
    workspace_id: str,
    slot: str,
    *,
    env: Any = None,
    tool_paths: Any = None,
    path_prepend: Any = None,
    dotenv: Any = None,
    venv: Any = None,
    secret_keys: frozenset[str] = frozenset(),
    issued_at: str = "",
    env_keep: Any = None,
) -> SlotFill:
    """REPLACE this slot's fill. A value for a key the declaration marks secret is refused.

    ``env_keep`` names env keys whose STORED values carry over (a value in ``env`` wins), so
    an editor that never sees a value can change one key without clearing the others. A kept
    name with no stored value is simply absent from the result — the caller reports it.
    """

    env_map = {**_kept_env(workspace_id, slot, env_keep), **_string_map(env, "env")}
    leaked = sorted(key for key in env_map if key in secret_keys)
    if leaked:
        raise SlotEnvRefused(REASON_SECRET_IN_ENV, f"declared secret, belongs in the slot's .env: {', '.join(leaked)}")
    prepend = list(path_prepend or [])
    if not all(isinstance(item, str) and item for item in prepend):
        raise SlotEnvRefused(REASON_INVALID_FILL, "path_prepend must be a list of paths")
    entry = {
        "tool_paths": _string_map(tool_paths, "tool_paths"),
        "env": env_map,
        "path_prepend": prepend,
        "dotenv": str(dotenv) if dotenv else None,
        "venv": str(venv) if venv else None,
        "bound_at": issued_at,
    }
    payload = _read()
    payload["schema_version"] = SLOT_ENV_SCHEMA_VERSION
    payload["workspaces"].setdefault(workspace_id, {})[slot] = entry
    _write(payload)
    return slot_fill(workspace_id, slot) or SlotFill()


def _kept_env(workspace_id: str, slot: str, env_keep: Any) -> dict[str, str]:
    names = list(env_keep or [])
    if not all(isinstance(name, str) and name for name in names):
        raise SlotEnvRefused(REASON_INVALID_FILL, "env_keep must be a list of key names")
    stored = (slot_fill(workspace_id, slot) or SlotFill()).env
    return {name: stored[name] for name in names if name in stored}


def drop_slot_fill(workspace_id: str, slot: str) -> bool:
    payload = _read()
    removed = (payload["workspaces"].get(workspace_id) or {}).pop(slot, None)
    if removed is None:
        return False
    _write(payload)
    return True


def _write(payload: dict[str, Any]) -> None:
    target = slot_env_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(target, payload, indent=2, sort_keys=True, mode=0o600)
