"""The phone wheels ``uv.lock`` cannot hold: pins by URL or repo path and sha256, per target, and their companions.

Fork-owned (row RT-PHONE-PILLOW-ANDROID, owner RULED 2026-11-17). ``agent_runtime/bundle_profiles/
phone_wheels.lock.json`` pins Flet's Android Pillow and the four image-library wheels it links; its
comment says why they are not in ``uv.lock``. It also pins ripgrep's matcher library,
``eternia-project-files-match`` (row RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID): a wheel built here by
``scripts/native/build_project_files_match.py`` and committed under ``crates/project_files_match/dist/``,
pinned by its repo-relative ``path`` instead of a ``url`` (owner RULED 2026-11-21: "yea commit them to the
hermes fork which is public"). Its ``loaded_by`` names the first-party module that loads it: an
undeclared distribution behind a guarded import is never shipped by the closure, so it ships wherever
it is pinned and that module ships (:func:`loaded_by`). Three readers, one file:

* the pool (:func:`pinned_blocks`): on a listed target a pinned name's ``uv.lock`` block is replaced
  by ``name @ url --hash=sha256:…``, and a pinned name the export lacks (a companion) is added, so
  ``uv pip install --require-hashes`` installs exactly the pinned wheel;
* the plan (:func:`with_companions`): a distribution's ``companions`` ship wherever it ships — the
  closure reaches ``pillow`` by its imports, never the libraries, which nothing imports;
* the gate (:func:`pinned_wheel`): a pinned distribution is judged by its pinned wheel, not ``uv.lock``,
  and every shared library in a wheel the repository holds is read for Android's 16 KB pages
  (:func:`alignment_problems`).

:func:`version_problems` keeps a pinned distribution's version equal to ``uv.lock``'s where the lock
has it (one version, the desktop's), save the ONE named phone-only exception in
:data:`PHONE_ONLY_VERSION_EXCEPTIONS` (``cryptography`` 48.0.0, owner RULED 2026-11-24), which still holds
the desktop's lock to its security floor.
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
    """normalised name -> ``{"version", "url" | "path", "sha256"}`` for every wheel pinned on ``target``."""
    return {name: {"version": entry["version"], **entry["targets"][target]}
            for name, entry in _wheels(doc).items() if target in entry.get("targets", {})}


def pin_location(pin: dict) -> str:
    """What the pool installs from: the pin's ``url``, or its repo-relative ``path`` as a file URL."""
    if "path" in pin:
        return (ROOT / pin["path"]).as_uri()
    return pin["url"]


def pinned_wheel(name: str, target: str | None, doc: dict | None = None) -> str | None:
    """The pinned wheel's file name for ``name`` on ``target``; None when it is not pinned there."""
    pin = pins(target, doc).get(_norm(name)) if target else None
    return pin_location(pin).rsplit("/", 1)[1] if pin else None


def loaded_by(modules: set[str] | None, target: str | None, doc: dict | None = None) -> set[str]:
    """The pinned names on ``target`` whose ``loaded_by`` module is in ``modules`` (every one when
    ``modules`` is None: the pool, which installs before the plan knows the modules)."""
    pinned = pins(target, doc) if target else {}
    # MUTATION: drop the ``modules`` test and the library ships in a bundle whose file tools do not
    # (test_phone_wheels: test_a_first_party_library_ships_only_with_the_module_that_loads_it).
    return {name for name, entry in _wheels(doc).items()
            if name in pinned and entry.get("loaded_by") and (modules is None or entry["loaded_by"] in modules)}


def alignment_problems(doc: dict | None = None) -> list[str]:
    """Every shared library aligned below 16 KB in a pinned wheel the repository holds (``path`` pins), and
    every such pin whose file is missing or is not its sha256. A ``url`` pin's bytes are read by the
    packager once its pool is installed (``scripts/bundle_profile_package.py``)."""
    import hashlib

    from scripts.bundles.elf_alignment import wheel_problems

    out = []
    for name, entry in sorted(_wheels(doc).items()):
        for target, pin in sorted(entry.get("targets", {}).items()):
            if "path" not in pin:
                continue
            wheel = ROOT / pin["path"]
            if not wheel.is_file():
                out.append(f"pinned_wheel_missing: {name} on {target}: {pin['path']} is not in the repository")
                continue
            if hashlib.sha256(wheel.read_bytes()).hexdigest() != pin["sha256"]:
                out.append(f"pinned_wheel_hash: {name} on {target}: {pin['path']} is not the pinned sha256")
                continue
            out += wheel_problems(wheel)
    return out


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
        return Block(name, f"{name} @ {pin_location(pin)}", "", (f"    --hash=sha256:{pin['sha256']}",))

    out = [pin_block(block.name) if block.name in pinned else block for block in blocks]
    present = {block.name for block in blocks}
    return out + [pin_block(name) for name in sorted(pinned) if name not in present]


#: The ONE phone-only exception to "a pinned wheel pins ``uv.lock``'s version": ``cryptography`` 48.0.0, the
#: newest Flet builds for Android and iOS (``pypi.flet.dev``), on phones only, for the phone listener's
#: certificate (``agent_runtime/gateway_tls.py``). Owner RULED 2026-11-24 on hermes row
#: ``RT-ACCOUNT-ONLY-YOUR-COMPUTER-CAN-OPEN-THE-CALL-TO-YOUR-PHONE-WHILE-ETERNIA-IS-IN-FRONT``: "for now use 48 but
#: before release we need to update it file it as a deffered release row". The release row is
#: ``RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR``: it removes this entry once
#: every phone wheel is at or above the floor. ``desktop_floor`` is ``pyproject.toml``'s (CVE-2026-69247,
#: GHSA-m2h6-j472-rp4c, GHSA-jwv3-5hgf-82ww), and the exception never lowers it: ``uv.lock`` below it, or the
#: excepted version pinned on a desktop target, is still a problem. Not a general loosening: one name, one
#: version, phone targets only.
PHONE_ONLY_VERSION_EXCEPTIONS: dict[str, dict[str, str]] = {
    "cryptography": {
        "version": "48.0.0",
        "desktop_floor": "50.0.0",
        "ruling": "owner RULED 2026-11-24 on RT-ACCOUNT-ONLY-YOUR-COMPUTER-CAN-OPEN-THE-CALL-TO-YOUR-PHONE-WHILE-"
                  "ETERNIA-IS-IN-FRONT",
        "row": "RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR",
    },
}

#: The phone targets (``scripts/bundles/targets.py``): the only ones an exception covers.
_PHONE_PREFIXES = ("android_", "ios_")


def _excepted(name: str, entry: dict, locked: str) -> list[str] | None:
    """The problems of a pin under its phone-only exception; None when ``name`` has none at this version."""
    from packaging.version import Version

    exception = PHONE_ONLY_VERSION_EXCEPTIONS.get(name)
    if exception is None or entry["version"] != exception["version"]:
        return None
    problems = []
    # MUTATION: drop this test and test_phone_wheels' desktop-floor test sees a lock at 48.0.0 pass.
    if Version(locked) < Version(exception["desktop_floor"]):
        problems.append(f"phone_wheel_version: {name} {locked} in uv.lock is under the desktop floor "
                        f"{exception['desktop_floor']}; the phone-only exception ({exception['row']}) never lowers it")
    desktop = sorted(t for t in entry.get("targets", {}) if not t.startswith(_PHONE_PREFIXES))
    # MUTATION: drop this test and test_phone_wheels' desktop-target test sees 48.0.0 pinned for linux-x64 pass.
    if desktop:
        problems.append(f"phone_wheel_version: {name} {entry['version']} is excepted on phones only, "
                        f"not on {', '.join(desktop)} ({exception['row']})")
    return problems


def version_problems(lock: dict[str, dict], doc: dict | None = None) -> list[str]:
    """A pinned distribution ``uv.lock`` also holds must pin the lock's version, save the one phone-only
    exception (:data:`PHONE_ONLY_VERSION_EXCEPTIONS`), which keeps the lock at its desktop floor."""
    problems = []
    for name, entry in sorted(_wheels(doc).items()):
        locked = (lock.get(name) or {}).get("version")
        if not locked:
            continue
        excepted = _excepted(name, entry, locked)
        if excepted is not None:
            problems += excepted
        elif locked != entry["version"]:
            problems.append(f"phone_wheel_version: {name} {entry['version']} is pinned for the phones, "
                            f"uv.lock pins {locked}: bump both together")
    return problems
