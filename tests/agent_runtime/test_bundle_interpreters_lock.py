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


def test_every_desktop_packaging_target_has_an_interpreter():
    """A phone target (manifest.PHONE_TARGETS, shipped or QA-only) is the host app's interpreter: never pinned here."""
    from agent_runtime.bundle_profiles.manifest import PHONE_TARGETS
    from scripts.bundles.targets import TARGETS

    pinned = set(_load(LOCK)["artifacts"])
    assert not pinned & set(PHONE_TARGETS), "a phone target must never carry an interpreter pin"
    assert pinned == set(TARGETS) - set(PHONE_TARGETS)


def test_the_pinned_minor_is_one_the_dependency_lock_resolves():
    """uv.lock resolves only for python >= 3.14; a bundle on another minor would install no core deps."""
    import tomllib

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    minor = tuple(int(p) for p in _load(LOCK)["version"].split("+")[0].split(".")[:2])
    assert lock["supported-markers"] == ["python_full_version >= '3.14'"]
    assert minor >= (3, 14)


def test_the_posix_family_prunes_what_the_windows_family_prunes():
    """L2.23: ``prune.posix`` was absent, so darwin/linux bundles shipped pip, idlelib,
    tkinter, turtledemo, include/ and the terminfo tree (2,871 files, ``N/``/``n/`` case
    twins) that the Windows list already drops. Every ``Lib/<x>`` the Windows family
    prunes has its ``lib/python3.X/<x>`` twin in the POSIX family, at the minor the
    layout's own POSIX site-packages names."""

    lock = _load(LOCK)
    posix_site = lock["layout"]["site_packages"]["posix"]  # lib/python3.X/site-packages
    stdlib = posix_site.rsplit("/", 1)[0]
    prune = lock["prune"]
    posix = set(prune.get("posix", []))
    expected = {
        f"{stdlib}/{pattern[len('Lib/'):]}" for pattern in prune["win32"] if pattern.startswith("Lib/")
    }
    assert expected and expected <= posix, sorted(expected - posix)
    assert {"share/terminfo", "include"} <= posix


def test_the_posix_family_prunes_the_unloaded_libpython_and_the_orphaned_tcl_tk():
    """RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED: python-build-standalone's Linux build ships
    lib/libpython3.X.so.1.0 (131 MB unstripped) beside a statically linked bin/python3.X that never
    loads it, and the tcl/tk tree tkinter's prune left orphaned. Matched the way Eternia's stage
    (scripts/ci/bundled_hermes/layout.py ``prune``) matches: fnmatch on the path under python/;
    nothing the interpreter runs from — the stdlib, lib-dynload, site-packages — may match."""
    import fnmatch

    lock = _load(LOCK)
    stdlib = lock["layout"]["site_packages"]["posix"].rsplit("/", 1)[0]  # lib/python3.X
    minor = stdlib.rsplit("python", 1)[1]
    posix = lock["prune"]["posix"]

    def pruned(rel: str) -> bool:
        return any(fnmatch.fnmatch(rel, pattern) for pattern in posix)

    shipped_by_the_archive = [
        f"lib/libpython{minor}.so", f"lib/libpython{minor}.so.1.0", "lib/libpython3.so",
        "lib/libtcl9.0.so", "lib/libtcl9tk9.0.so", "lib/itcl4.3.8", "lib/thread3.0.6",
        "lib/tcl9", "lib/tcl9.0", "lib/tk9.0",
    ]
    assert [rel for rel in shipped_by_the_archive if not pruned(rel)] == []
    kept = [f"bin/python{minor}", "bin/python3", stdlib, f"{stdlib}/ssl.py",
            f"{stdlib}/lib-dynload", f"{stdlib}/site-packages", "lib/pkgconfig"]
    assert [rel for rel in kept if pruned(rel)] == []
