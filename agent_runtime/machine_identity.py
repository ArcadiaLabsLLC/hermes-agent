"""One machine id per PC, kept with the shared namespaces folder (rows ``RT-MACHINE-ID``,
``RT-SLOT-MACHINE-ID-IS-NAMESPACE-INSTALL``).

Plan ``docs/agent-runtime-harness/planned/naming-and-address-map-2026-10-25.md``, ruling 3: the
machine id and the install id are split. The install id (``gateway/install.json`` under a store
root, :mod:`agent_runtime.gateway_identity`) names ONE namespace's data root and is re-minted by a
reseed; it stays per namespace. The machine id names the PC: one file,
``<namespaces folder>/machine-id.json``, outside both installs' base roots (``namespaces_dir``
refuses containment either way), so the Developer Edition and the bundled harness read the same id.
The file name is not a namespace id (it holds a dot), so ``hermes namespace list`` skips it.

Stdlib + the bootstrap's path rules only; never raises from :func:`read_machine_id`.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from hermes_cli._namespace_bootstrap import NamespaceRefused, base_root, namespaces_dir

__layer__ = "stores"

MACHINE_ID_FILENAME = "machine-id.json"
MACHINE_ID_SCHEMA = 1
MACHINE_ID_PREFIX = "mach_"


#: path -> id, once read or minted: a machine id never changes while a process lives.
_KNOWN: dict[str, str] = {}


class MachineIdentityUnavailable(RuntimeError):
    """The machine id could not be read or minted; ``state`` names why."""

    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = state


def machine_id_path(env: Mapping[str, str] | None = None) -> Path:
    """``<namespaces folder>/machine-id.json`` for this process's install (refusals propagate)."""

    source = os.environ if env is None else env
    return namespaces_dir(source, base_root(source)) / MACHINE_ID_FILENAME


def _decode_machine_record(raw: str) -> str | None:
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return None
    value = record.get("machine_id") if isinstance(record, dict) else None
    if isinstance(value, str) and value.startswith(MACHINE_ID_PREFIX) and len(value) > len(MACHINE_ID_PREFIX):
        return value
    return None


def read_machine_id(env: Mapping[str, str] | None = None) -> str | None:
    """The machine id WITHOUT minting one; ``None`` when there is none or it cannot be read."""

    try:
        path = machine_id_path(env)
    except NamespaceRefused:
        return None
    if str(path) in _KNOWN:
        return _KNOWN[str(path)]
    try:
        value = _decode_machine_record(path.read_text(encoding="utf-8-sig"))
    except OSError:
        return None
    if value is not None:
        _KNOWN[str(path)] = value
    return value


def ensure_machine_id(env: Mapping[str, str] | None = None) -> str:
    """The machine id, minted once (``O_EXCL``) when absent; a race adopts the winner's id."""

    try:
        path = machine_id_path(env)
    except NamespaceRefused as exc:
        raise MachineIdentityUnavailable(f"error:{exc.reason.value}") from exc
    existing = read_machine_id(env)
    if existing is not None:
        return existing
    if path.is_file() and path.stat().st_size > 0:
        raise MachineIdentityUnavailable("error:unreadable")  # a record we cannot parse is never overwritten
    record = {"schema": MACHINE_ID_SCHEMA, "machine_id": f"{MACHINE_ID_PREFIX}{uuid.uuid4().hex}",
              "created_at": datetime.now(UTC).isoformat(timespec="seconds")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():  # zero bytes: a mint killed mid-write holds no id, so heal it
            path.unlink()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        adopted = read_machine_id(env)
        if adopted is None:
            raise MachineIdentityUnavailable("error:race_unreadable") from None
        return adopted
    except OSError as exc:
        raise MachineIdentityUnavailable(f"error:{type(exc).__name__}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
    _KNOWN[str(path)] = record["machine_id"]
    return record["machine_id"]
