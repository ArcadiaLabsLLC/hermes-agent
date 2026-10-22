"""The store epoch: the one integer an older edition compares before it opens a shared namespace.

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/EDITION_SWITCH_NAMESPACE_STORE_2026-10-20.md`` §4
(row ``RT-STORE-EPOCH``). Owner ruling 2026-10-20: guard on a BREAKING-change epoch, never on the
version; an additive change never raises it. Both editions open one shared namespace, so the store
records which epoch last shaped it and a build that reads an older shape refuses to open a newer one.

* :data:`STORE_EPOCH` — the epoch THIS build reads and writes; always ``1 + count(breaking entries)``.
* :data:`MIGRATION_REGISTRY` — one entry per store-shape change: ``{id, date, store, breaking, reason}``,
  and a breaking entry also carries ``raises_to`` (the epoch it raised the store to).
* ``namespace.json`` carries ``epoch {value, raised_at, raised_by{commit, edition, hermes_version}}``
  and ``last_written_by {commit, edition, hermes_version, at}`` (provenance, never compared). A missing
  ``epoch`` block is epoch 0; a block this build cannot parse is NEWER (fail closed).
* :func:`decide` is the verdict table; :func:`guard` applies it to a manifest and stamps on an open.
* ``python -m agent_runtime.store_epoch`` prints ``{"schema": 1, "store_epoch": N}`` for the release lane.

Stdlib only and importable before any store I/O: ``hermes_cli._namespace_bootstrap`` loads this file
without importing the ``agent_runtime`` package (whose ``__init__`` imports the models), so it must
never import from ``agent_runtime``.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__layer__ = "stores"

CONSENT_ENV = "HERMES_STORE_EPOCH_CONSENT"
LAUNCHER_ENV = "HERMES_LAUNCHER_SPAWNED"
PRINT_SCHEMA = 1

#: Every store-shape change that landed, oldest first. Append; never rewrite an entry.
#: ``pins_sha256`` is :func:`pins_digest` of ``store_shape_pins.json`` AFTER the change: the newest
#: entry must name the pins in the tree, so re-pinning a changed shape forces a new entry
#: (``tests/agent_runtime/test_store_epoch_gate.py``, row RT-STORE-EPOCH-GATE).
MIGRATION_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "id": "store-epoch-baseline",
        "date": "2026-10-20",
        "store": "all",
        "breaking": False,
        "reason": "epoch 1 is the store shape the guard was introduced over; every older namespace reads it",
        "pins_sha256": "f4ecdffef54e3dcde754394adeaa4a6ae694f41b0de97b5f8edaad2030288aef",
    },
    {
        "id": "course-checkouts-dir",
        "date": "2026-10-21",
        "store": "all",
        "breaking": False,
        "reason": "additive: paths.course_dir / course_checkout_dir / course_worktrees_dir under a new "
                  "top-level courses/ (git course clones); no existing path moves, an older edition never reads it",
        "pins_sha256": "a79581ac1ebbd865f268c67c1488d502de738fd9309ed7bbefd741a9a51286ea",
    },
    {
        "id": "work-worktree-keyed-by-checkout",
        "date": "2026-10-21",
        "store": "all",
        "breaking": False,
        "reason": "paths.work_worktree_dir moves from worktrees/<slot> to worktrees/<slot>-<checkout_token> and "
                  "work_worktrees_dir names the parent (lane w1021j-work); a worktree is a derived cut of a slot "
                  "checkout, so an older edition re-cuts at its own path and the newer one reads the old as a "
                  "stale-worktree receipt; nothing is lost or misread",
        "pins_sha256": "446e0d76d5fdf603281ad3f747e1febc813ad6d7d625ffbe6f60e6af5ed5ebd7",
    },
)

#: ``1 + count(breaking entries)`` — ``tests/agent_runtime/test_store_epoch_gate.py`` holds it to that.
STORE_EPOCH = 1

#: The store-shape pins the gate compares with the tree (``SCHEMA_VERSION``, the ``SCHEMA_SQL`` digest,
#: the turn-record and runtime schema versions, every ``models.py`` ``schema_version`` default and the
#: ``paths.py`` path-table digest).
PINS_PATH = Path(__file__).resolve().with_name("store_shape_pins.json")


def load_pins(path: Path | None = None) -> dict[str, Any]:
    return json.loads((PINS_PATH if path is None else path).read_text(encoding="utf-8"))["pins"]


def pins_digest(pins: Mapping[str, Any]) -> str:
    """sha256 of the canonical JSON of *pins* — what a registry entry's ``pins_sha256`` names."""
    import hashlib

    return hashlib.sha256(json.dumps(dict(pins), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


VERDICT_OK = "ok"
VERDICT_RAISE = "raise"
VERDICT_NEWER = "newer"
VERDICT_CONSENT_REQUIRED = "consent_required"
VERDICT_UNSCOPED = "unscoped"

REFUSAL_NEWER = "namespace_epoch_newer"
REFUSAL_CONSENT_REQUIRED = "namespace_epoch_consent_required"
_REFUSALS = {VERDICT_NEWER: REFUSAL_NEWER, VERDICT_CONSENT_REQUIRED: REFUSAL_CONSENT_REQUIRED}

#: The tree this module runs from (its build stamp names the edition and commit).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def breaking_entries(registry: tuple[dict[str, Any], ...] | None = None) -> list[dict[str, Any]]:
    return [entry for entry in (MIGRATION_REGISTRY if registry is None else registry) if entry.get("breaking") is True]


def stored_epoch(manifest: Mapping[str, Any]) -> int | None:
    """The epoch a manifest records: 0 when it has no block, ``None`` when the block is unparseable."""
    if "epoch" not in manifest:
        return 0
    block = manifest.get("epoch")
    value = block.get("value") if isinstance(block, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def would_raise(stored: int, registry: tuple[dict[str, Any], ...] | None = None) -> bool:
    """True when this build's registry holds a breaking entry above *stored*."""
    return any(int(entry.get("raises_to") or 0) > stored for entry in breaking_entries(registry))


def consented(env: Mapping[str, str], mine: int | None = None) -> bool:
    """Consent to raise is the launcher's: spawned by it, naming exactly this build's epoch."""
    mine = STORE_EPOCH if mine is None else mine
    return str(env.get(LAUNCHER_ENV) or "") == "1" and str(env.get(CONSENT_ENV) or "") == str(mine)


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: str
    stored: int | None
    mine: int

    @property
    def refusal(self) -> str | None:
        return _REFUSALS.get(self.verdict)

    @property
    def opens(self) -> bool:
        return self.verdict in (VERDICT_OK, VERDICT_RAISE, VERDICT_UNSCOPED)

    def payload(self) -> dict[str, Any]:
        return {"stored": self.stored, "mine": self.mine, "verdict": self.verdict}


def decide(stored: int | None, env: Mapping[str, str], *, mine: int | None = None,
           registry: tuple[dict[str, Any], ...] | None = None) -> Decision:
    """The §4 verdict table. Pure; *mine* / *registry* default to this build's, read at call time."""
    mine = STORE_EPOCH if mine is None else mine
    if stored is None or stored > mine:
        return Decision(VERDICT_NEWER, stored, mine)
    if stored == mine or not would_raise(stored, registry):
        return Decision(VERDICT_OK, stored, mine)
    if consented(env, mine):
        return Decision(VERDICT_RAISE, stored, mine)
    return Decision(VERDICT_CONSENT_REQUIRED, stored, mine)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def provenance() -> dict[str, Any]:
    """``{commit, edition, hermes_version}`` of the executing tree, from its build stamp. Never raises."""
    stamp: dict[str, Any] = {}
    try:
        from hermes_cli.steward import read_install_stamp

        stamp = read_install_stamp(_PROJECT_ROOT)
    except Exception:
        stamp = {}
    return {
        "commit": stamp.get("commit") if isinstance(stamp.get("commit"), str) else None,
        "edition": "bundled" if stamp.get("payload") == "bundled" else "developer",
        "hermes_version": stamp.get("baseVersion") if isinstance(stamp.get("baseVersion"), str) else None,
    }


def epoch_block(value: int | None = None, origin: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The ``epoch`` block a store gets when it is created or raised."""
    return {"value": STORE_EPOCH if value is None else value, "raised_at": _now(), "raised_by": dict(origin or provenance())}


def last_written_block(origin: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {**(origin or provenance()), "at": _now()}


def _read_manifest(manifest_path: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return {"epoch": "unreadable"}  # a manifest this build cannot read is a store it cannot vouch for
    return record if isinstance(record, dict) else {"epoch": "unreadable"}


def write_manifest(manifest_path: Path, record: Mapping[str, Any]) -> None:
    path = Path(manifest_path)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dict(record), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def stamped(record: Mapping[str, Any], *, raise_to: int | None = None,
            origin: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """*record* with ``last_written_by`` refreshed and, when *raise_to* is given, the epoch raised."""
    who = dict(origin or provenance())
    out = {**record, "last_written_by": last_written_block(who)}
    if raise_to is not None:
        out["epoch"] = epoch_block(raise_to, who)
    return out


def guard(manifest_path: Path | None, env: Mapping[str, str], *, write: bool = True) -> Decision:
    """Decide whether this build may open the namespace whose manifest is *manifest_path*.

    No manifest (the base root, or a namespace not created yet) is ``unscoped``: there is no shared
    store to guard. A refusal writes nothing. An open with *write* stamps ``last_written_by``, and a
    consented raise also stamps ``epoch.value = STORE_EPOCH``.
    """
    record = _read_manifest(manifest_path) if manifest_path is not None else None
    if record is None:
        return Decision(VERDICT_UNSCOPED, None, STORE_EPOCH)
    decision = decide(stored_epoch(record), env)
    if decision.opens and write:
        write_manifest(manifest_path, stamped(record, raise_to=STORE_EPOCH if decision.verdict == VERDICT_RAISE else None))
    return decision


EXIT_REFUSED = 2


def namespace_decision(env: Mapping[str, str], *, write: bool = True) -> Decision:
    """The decision for the namespace *env* names (``unscoped`` for the base root)."""
    from hermes_cli._namespace_bootstrap import layout, namespace_stamp

    ns_id = namespace_stamp(env)
    manifest = layout(ns_id, env, long_paths=True).manifest_path if ns_id else None
    return guard(manifest, env, write=write)


def refuse_unreadable_store(emit: Callable[[dict[str, Any]], None], env: Mapping[str, str] | None = None,
                            *, write: bool = True) -> int | None:
    """The process-entry guard: ``None`` when the store opens, else :data:`EXIT_REFUSED` after one frame.

    The serve runs it as its first act after ``booting`` — before the root anchor, the skill install,
    the install identity and the serve token, every one of which writes into the store — so a refusal
    writes nothing. (Plan §4 says "after the socket lock"; in this tree the store is written before
    the socket lock is taken and a stdio serve takes none, so the guard runs earlier, not later.)
    The conversation worker runs it with ``write=False``: its serve, the same build, stamped this boot.
    """
    source = os.environ if env is None else env
    decision = namespace_decision(source, write=write)
    if decision.refusal is None:
        return None
    emit({"event": "namespace_refused", "pid": os.getpid(), "reason": decision.refusal,
          "namespace": str(source.get("HERMES_NAMESPACE") or ""), "epoch": decision.payload()})
    try:
        sys.stderr.write(json.dumps({"ok": False, "error": "namespace_refused", "reason": decision.refusal,
                                     "epoch": decision.payload()}) + "\n")
        sys.stderr.flush()
    except Exception:  # the frame is the receipt; stderr is a second audience
        pass
    return EXIT_REFUSED


def main() -> int:
    sys.stdout.write(json.dumps({"schema": PRINT_SCHEMA, "store_epoch": STORE_EPOCH}) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
