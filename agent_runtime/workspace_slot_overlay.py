"""The repo-slot ENVIRONMENT overlay — what a command under a bound slot runs with (build plan §3.3).

Owner call 8e: the slot environment applies to EVERY command whose cwd is under an
assigned slot's bound path, not only builds — "a build" is only the recognizer's label for
some of those commands. ONE overlay function, :func:`env_overlay`, applied through ONE seam:
the fork's single additive call in upstream ``tools/environments/local.py`` (Fork Boundary
Map "Seams"), :func:`apply_slot_env_overlay`, which reads the :data:`_SCOPE` contextvar the
mission-chat turn sets beside its workdir (``persona_runtime``).

The overlay of a slot is this machine's fill (``workspace_slot_env``): ``path_prepend`` in
front of ``PATH``, ``env`` merged, the slot's ``.env`` loaded — VALUES FROM THE FILE, never
from the record, which refuses secrets (``secret_in_env``) — and a ``venv`` activated by
prepending its ``Scripts`` / ``bin``. A cwd under no bound slot gets nothing.

Deliberately its own light module: the upstream file imports it on every spawn, so with no
scope set :func:`apply_slot_env_overlay` returns the env untouched before importing anything.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

__layer__ = "stores"

ENV_SOURCE_SLOT_PREFIX = "slot:"
_DOTENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


@dataclass(frozen=True)
class SlotBinding:
    """One slot bound on this machine: which workspace, which slot, the checkout."""

    workspace_id: str
    slot: str
    path: str


@dataclass(frozen=True)
class SlotEnvScope:
    """The turn's bound slots and the directory its commands run in."""

    bindings: tuple[SlotBinding, ...]
    cwd: str


_SCOPE: ContextVar[SlotEnvScope | None] = ContextVar("hermes_slot_env_scope", default=None)


@contextmanager
def slot_env_scope(bindings: Iterable[SlotBinding], cwd: Any) -> Iterator[None]:
    """Set the scope for the turn's run; every child spawned inside it sees the overlay."""

    bound = tuple(bindings)
    token = _SCOPE.set(SlotEnvScope(bound, str(cwd or "")) if bound and cwd else None)
    try:
        yield
    finally:
        _SCOPE.reset(token)


@dataclass(frozen=True)
class SlotEnvOverlay:
    """What a command under ``slot`` runs with on this machine."""

    workspace_id: str
    slot: str
    path_prepend: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    dotenv_keys: tuple[str, ...] = ()
    tool_paths: dict[str, str] = field(default_factory=dict)

    @property
    def env_source(self) -> str:
        return f"{ENV_SOURCE_SLOT_PREFIX}{self.slot}"

    @property
    def keys(self) -> frozenset[str]:
        """Every env key this overlay sets (PATH counts when it prepends)."""

        return frozenset(self.env) | (frozenset({"PATH"}) if self.path_prepend else frozenset())

    def apply(self, env: dict[str, str]) -> dict[str, str]:
        out = dict(env)
        out.update(self.env)
        if self.path_prepend:
            key = next((k for k in out if k.upper() == "PATH"), "PATH")
            head = [entry for entry in self.path_prepend if entry]
            rest = [entry for entry in str(out.get(key, "")).split(os.pathsep) if entry and entry not in head]
            out[key] = os.pathsep.join(head + rest)
        return out


def _deepest(cwd: str, bindings: Iterable[SlotBinding]) -> SlotBinding | None:
    try:
        target = os.path.normcase(os.path.realpath(cwd))
    except (OSError, ValueError):
        return None
    best, best_len = None, -1
    for binding in bindings:
        root = os.path.normcase(os.path.realpath(binding.path)).rstrip(os.sep)
        if (target == root or target.startswith(root + os.sep)) and len(root) > best_len:
            best, best_len = binding, len(root)
    return best


def read_dotenv(path: Path) -> dict[str, str]:
    """``KEY=VALUE`` lines of a ``.env`` file (quotes stripped); an unreadable file is empty."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    values = {}
    for line in lines:
        match = _DOTENV_LINE_RE.match(line)
        if match and not line.lstrip().startswith("#"):
            value = match.group(2)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[match.group(1)] = value
    return values


def _venv_bin(venv: str) -> str:
    return str(Path(venv) / ("Scripts" if os.name == "nt" else "bin"))


def overlay_for(binding: SlotBinding) -> SlotEnvOverlay:
    """The overlay of one bound slot: the machine fill, the slot's ``.env``, the venv."""

    from .workspace_slot_env import slot_fill
    from .workspace_slots import live_slots, load_document, secret_keys

    fill = slot_fill(binding.workspace_id, binding.slot)
    declared = live_slots(load_document(binding.workspace_id)).get(binding.slot) or {}
    dotenv_name = (fill.dotenv if fill else None) or ((declared.get("toolchain") or {}).get("dotenv") or {}).get("path")
    dotenv = read_dotenv(Path(binding.path) / dotenv_name) if dotenv_name else {}
    # A key the declaration marks secret reaches a command ONLY from the slot's .env — never
    # from the machine record, even one edited by hand past the ``secret_in_env`` door.
    secret = secret_keys(declared)
    recorded = {key: value for key, value in (fill.env if fill else {}).items() if key not in secret}
    env = {**recorded, **dotenv}
    prepend = list(fill.path_prepend if fill else ())
    if fill and fill.venv:
        prepend.insert(0, _venv_bin(fill.venv))
        env["VIRTUAL_ENV"] = fill.venv
    return SlotEnvOverlay(binding.workspace_id, binding.slot, tuple(prepend), env, tuple(sorted(dotenv)),
                          dict(fill.tool_paths) if fill else {})


def env_overlay(cwd: Any, bindings: Iterable[SlotBinding] | None = None) -> SlotEnvOverlay | None:
    """The overlay for a command run in ``cwd``: the deepest bound slot it sits under, else None.

    ``bindings`` defaults to the active turn's scope, else every slot bound on this machine
    (a Restart from the console runs outside any turn).
    """

    if bindings is None:
        scope = _SCOPE.get()
        if scope is not None:
            bindings = scope.bindings
        else:
            from .workspace_slots import authorized_roots_bound_here

            bindings = [SlotBinding(b.workspace_id, b.slot, str(b.path)) for b in authorized_roots_bound_here()]
    binding = _deepest(str(cwd or ""), bindings)
    return None if binding is None else overlay_for(binding)


def apply_slot_env_overlay(env: dict[str, str]) -> dict[str, str]:
    """THE seam's callee: overlay ``env`` when a turn's scope is set and its cwd is under a slot."""

    scope = _SCOPE.get()
    if scope is None:
        return env
    overlay = env_overlay(scope.cwd, scope.bindings)
    return env if overlay is None else overlay.apply(env)
