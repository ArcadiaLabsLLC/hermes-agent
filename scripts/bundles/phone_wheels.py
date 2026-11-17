"""The phone wheels ``uv.lock`` cannot hold: pins by URL and sha256, per target, and their companions.

Fork-owned (row RT-PHONE-PILLOW-ANDROID, owner RULED 2026-11-17). ``agent_runtime/bundle_profiles/
phone_wheels.lock.json`` pins Flet's Android Pillow and the four image-library wheels it links; its
comment says why they are not in ``uv.lock``. Three readers, one file:

* the pool (:func:`pinned_blocks`): on a listed target a pinned name's ``uv.lock`` block is replaced
  by ``name @ url --hash=sha256:…``, and a pinned name the export lacks (a companion) is added, so
  ``uv pip install --require-hashes`` installs exactly the pinned wheel;
* the plan (:func:`with_companions`): a distribution's ``companions`` ship wherever it ships — the
  closure reaches ``pillow`` by its imports, never the libraries, which nothing imports;
* the gate (:func:`pinned_wheel`): a pinned distribution is judged by its pinned wheel, not ``uv.lock``.

:func:`version_problems` keeps a pinned distribution's version equal to ``uv.lock``'s where the lock
has it (one version, the desktop's).
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.bundle_profile_closure import ROOT, _norm
from scripts.bundles.requirement_blocks import Block

PHONE_WHEELS = ROOT / "agent_runtime" / "bundle_profiles" / "phone_wheels.lock.json"


def load(path: Path = PHONE_WHEELS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _wheels(doc: dict | None) -> dict[str, dict]:
    return {_norm(name): entry for name, entry in (load() if doc is None else doc)["wheels"].items()}


def pins(target: str, doc: dict | None = None) -> dict[str, dict]:
    """normalised name -> ``{"version", "url", "sha256"}`` for every wheel pinned on ``target``."""
    return {name: {"version": entry["version"], **entry["targets"][target]}
            for name, entry in _wheels(doc).items() if target in entry.get("targets", {})}


def pinned_wheel(name: str, target: str | None, doc: dict | None = None) -> str | None:
    """The pinned wheel's file name for ``name`` on ``target``; None when it is not pinned there."""
    pin = pins(target, doc).get(_norm(name)) if target else None
    return pin["url"].rsplit("/", 1)[1] if pin else None


def with_companions(names: set[str], target: str, doc: dict | None = None) -> set[str]:
    """``names`` plus the companions of each name pinned on ``target`` (themselves pinned there)."""
    wheels, pinned = _wheels(doc), pins(target, doc)
    extra = {_norm(c) for name in names if name in pinned for c in wheels[name].get("companions", ())}
    unpinned = sorted(c for c in extra if c not in pinned)
    if unpinned:
        raise ValueError(f"phone_wheels.lock.json: companions not pinned on {target}: {unpinned}")
    return set(names) | extra


def pinned_blocks(blocks: list[Block], target: str, doc: dict | None = None) -> list[Block]:
    """The export's blocks with every name pinned on ``target`` replaced by its pin, and every pinned
    name the export lacks appended. Another target's blocks are left as the export has them."""
    pinned = pins(target, doc)

    def pin_block(name: str) -> Block:
        pin = pinned[name]
        return Block(name, f"{name} @ {pin['url']}", "", (f"    --hash=sha256:{pin['sha256']}",))

    out = [pin_block(block.name) if block.name in pinned else block for block in blocks]
    present = {block.name for block in blocks}
    return out + [pin_block(name) for name in sorted(pinned) if name not in present]


def version_problems(lock: dict[str, dict], doc: dict | None = None) -> list[str]:
    """A pinned distribution ``uv.lock`` also holds must pin the lock's version."""
    problems = []
    for name, entry in sorted(_wheels(doc).items()):
        locked = (lock.get(name) or {}).get("version")
        if locked and locked != entry["version"]:
            problems.append(f"phone_wheel_version: {name} {entry['version']} is pinned for the phones, "
                            f"uv.lock pins {locked}: bump both together")
    return problems
