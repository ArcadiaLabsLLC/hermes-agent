"""A breaking store migration must raise the store epoch — as a mechanism (row RT-STORE-EPOCH-GATE).

Launcher plan ``EDITION_SWITCH_NAMESPACE_STORE_2026-10-20.md`` §4. ``agent_runtime/store_shape_pins.json``
pins the store shape an older edition reads; the pins are read from the RUNTIME (the imported
constants, the dataclass defaults, the path builders called), never from a source spelling.

* the pins equal the tree, so a shape change cannot land unpinned;
* the newest :data:`MIGRATION_REGISTRY` entry names the pins in the tree (``pins_sha256``), so a
  re-pin cannot land without a new entry that declares ``breaking`` true or false, with a reason;
* :data:`STORE_EPOCH` is ``1 + count(breaking entries)`` and each breaking entry names the epoch it
  raised to, so neither the constant nor a ``breaking: true`` can move alone.

To re-pin: write the JSON this file's failure prints into ``store_shape_pins.json`` and append a
registry entry whose ``pins_sha256`` is the digest it prints.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from agent_runtime import store_epoch as se

pytestmark = pytest.mark.gate

_ID = "i" * 32
_STORE_ROOT_ARGS = {"gateway_dir", "install_record_path"}
_ENTRY_KEYS = {"id", "date", "store", "breaking", "reason", "pins_sha256"}


def _path_table(monkeypatch, root: Path) -> dict[str, str]:
    """name -> the store-relative path each public ``paths`` builder returns (the budget test's walk)."""
    from agent_runtime import paths

    monkeypatch.delenv("HERMES_NAMESPACE", raising=False)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root))
    out: dict[str, str] = {}
    for name, fn in inspect.getmembers(paths, inspect.isfunction):
        if fn.__module__ != paths.__name__ or name.startswith("_"):
            continue
        if name in _STORE_ROOT_ARGS:
            built = fn(root)
        else:
            signature = inspect.signature(fn)
            if "Path" not in str(signature.return_annotation):
                continue
            params = list(signature.parameters.values())
            if any("Path" in str(p.annotation) for p in params):
                continue
            built = fn(*[_ID for _ in params])
        out[name] = Path(built).relative_to(root).as_posix() if Path(built).is_relative_to(root) else "<outside>"
    return out


def current_pins(monkeypatch, root: Path) -> dict[str, object]:
    import hermes_state_common
    from agent_runtime import migrations, mission_chat_phases, models

    defaults = {}
    for name, cls in inspect.getmembers(models, inspect.isclass):
        if cls.__module__ != models.__name__ or not dataclasses.is_dataclass(cls):
            continue
        for item in dataclasses.fields(cls):
            if item.name == "schema_version":
                defaults[name] = item.default
    table = _path_table(monkeypatch, root)
    return {
        "hermes_state_common.SCHEMA_VERSION": hermes_state_common.SCHEMA_VERSION,
        "hermes_state_common.SCHEMA_SQL.sha256": hashlib.sha256(hermes_state_common.SCHEMA_SQL.encode()).hexdigest(),
        "mission_chat_phases.TURN_RECORD_SCHEMA_VERSION": mission_chat_phases.TURN_RECORD_SCHEMA_VERSION,
        "migrations.CURRENT_RUNTIME_SCHEMA_VERSION": migrations.CURRENT_RUNTIME_SCHEMA_VERSION,
        "models.schema_version_defaults": dict(sorted(defaults.items())),
        "paths.path_table.sha256": hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest(),
        "paths.path_table.count": len(table),
    }


def _repin_hint(pins: dict[str, object]) -> str:
    return ("re-pin store_shape_pins.json to\n" + json.dumps({"schema": 1, "pins": pins}, indent=2, sort_keys=True)
            + f"\nand append a MIGRATION_REGISTRY entry with pins_sha256 {se.pins_digest(pins)!r}")


def test_the_pins_equal_the_tree(monkeypatch, tmp_path):
    pins = current_pins(monkeypatch, tmp_path / "agent-runtime")
    assert len(pins["models.schema_version_defaults"]) > 10  # positive control: the walk found the models
    assert pins["paths.path_table.count"] > 80  # and the path builders
    assert se.load_pins() == pins, _repin_hint(pins)


def test_the_newest_registry_entry_declares_the_pinned_shape():
    newest = se.MIGRATION_REGISTRY[-1]
    assert newest["pins_sha256"] == se.pins_digest(se.load_pins()), (
        "store_shape_pins.json moved with no MIGRATION_REGISTRY entry declaring it (breaking true/false + "
        f"reason); the new entry's pins_sha256 is {se.pins_digest(se.load_pins())!r}")


def test_store_epoch_is_one_plus_the_breaking_entries():
    breaking = se.breaking_entries()
    assert se.STORE_EPOCH == 1 + len(breaking)
    assert [entry.get("raises_to") for entry in breaking] == list(range(2, 2 + len(breaking)))


def test_every_registry_entry_is_a_declaration():
    ids = [entry["id"] for entry in se.MIGRATION_REGISTRY]
    assert len(ids) == len(set(ids))
    for entry in se.MIGRATION_REGISTRY:
        assert _ENTRY_KEYS <= set(entry), entry
        assert isinstance(entry["breaking"], bool) and str(entry["reason"]).strip(), entry
        assert ("raises_to" in entry) is entry["breaking"], entry
