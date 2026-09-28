"""The shipped core's HTTP stack stays above its advisory fix floors (bundled-desktop D4 gate).

``pyproject.toml`` pins ``httpx2`` in upstream's ``mcp`` / ``computer-use`` extras and the
``dev`` group. The fork carries a higher pin than upstream's 2.7.0 (the pyproject comment
above the ``mcp`` extra); an upstream merge that takes upstream's line back would reship
CVE-2026-84378..84382 with nothing but the networked OSV scan to notice. This is the
hermetic floor: every declared pin and every locked version.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
#: distribution -> the first release carrying every advisory fix the D4 scan reported
FLOORS = {"httpx2": Version("2.12.0"), "httpcore2": Version("2.10.0")}


def _declared(metadata: dict) -> list[tuple[str, Requirement]]:
    groups = {**metadata["project"]["optional-dependencies"], **metadata["dependency-groups"]}
    specs = [("dependencies", spec) for spec in metadata["project"]["dependencies"]]
    specs += [(group, spec) for group, rows in groups.items() for spec in rows if isinstance(spec, str)]
    return [(where, req) for where, spec in specs if (req := Requirement(spec)).name in FLOORS]


def test_declared_pins_and_locked_versions_clear_the_advisory_floors():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    declared = _declared(metadata)
    assert {where for where, _ in declared} >= {"mcp", "computer-use", "dev"}
    for where, requirement in declared:
        for spec in requirement.specifier:
            assert Version(spec.version) >= FLOORS[requirement.name], (where, str(requirement))
    locked = {row["name"]: Version(row["version"]) for row in lock["package"] if row["name"] in FLOORS}
    assert locked.keys() == FLOORS.keys()
    for name, version in locked.items():
        assert version >= FLOORS[name], (name, str(version))
