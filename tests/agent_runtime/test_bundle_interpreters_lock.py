"""The bundled interpreter lock is PM's python pin, copied for the Launcher installer — never a second pin."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "agent_runtime" / "bundle_profiles" / "interpreters.lock.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_bundle_target_equals_pms_python_pin():
    lock = _load(LOCK)
    pm_python = _load(ROOT / "pm" / "lock.json")["packages"]["python"]
    assert lock["version"] == pm_python["version"]
    assert lock["artifacts"], "the lock names no target"
    for target, artifact in lock["artifacts"].items():
        assert artifact == pm_python["artifacts"][target], target


def test_every_packaging_target_has_an_interpreter():
    from scripts.bundle_profile_package import TARGETS

    assert set(_load(LOCK)["artifacts"]) == set(TARGETS)


def test_the_pinned_minor_is_one_the_dependency_lock_resolves():
    """uv.lock resolves only for python >= 3.14; a bundle on another minor would install no core deps."""
    import tomllib

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    minor = tuple(int(p) for p in _load(LOCK)["version"].split("+")[0].split(".")[:2])
    assert lock["supported-markers"] == ["python_full_version >= '3.14'"]
    assert minor >= (3, 14)
