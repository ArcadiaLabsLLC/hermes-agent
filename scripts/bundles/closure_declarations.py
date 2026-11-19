"""Declarations and lock facts for the bundle closure walk (``bundle_profile_closure.py``).

What ``pyproject.toml`` declares for the bundle target and what ``uv.lock`` pins: the
requirement parse, the declared base and extras, the lock read and its stale-site check.
Split out of ``scripts/bundle_profile_closure.py`` (W0-G1 size ceiling); that script
re-exports every name here, so its callers are unchanged.
"""

from __future__ import annotations

import functools
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


#: The bundle target: markers are evaluated for the interpreter the installer ships.
TARGET_ENV = {
    "sys_platform": "win32", "platform_system": "Windows", "platform_machine": "AMD64",
    "os_name": "nt", "python_version": "3.14", "python_full_version": "3.14.0",
    "implementation_name": "cpython", "platform_python_implementation": "CPython",
    "platform_release": "10", "extra": "",
}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@functools.cache
def _req(raw: str):
    """One parse per requirement string per process: callers only read the result, and a
    graph walk meets the same strings again and again (FORK-BUNDLE-PROFILES-SDK-PACK-TEST-HANGS:
    the re-parse was most of a test that ran past its 30 s timeout on a starved core)."""
    from packaging.requirements import Requirement

    return Requirement(raw)


def declared(path: Path = ROOT / "pyproject.toml", env: dict | None = None) -> tuple[set[str], dict[str, set[str]]]:
    """-> (base distribution names, extra -> distribution names), markers evaluated for the target."""
    project = tomllib.loads(path.read_text(encoding="utf-8-sig"))["project"]
    self_name = _norm(project["name"])
    env = TARGET_ENV if env is None else env

    def names(raws):
        out, refs = set(), set()
        for raw in raws:
            req = _req(raw)
            if req.marker is not None and not req.marker.evaluate(env):
                continue
            if _norm(req.name) == self_name:
                refs.update(req.extras)
            else:
                out.add(_norm(req.name))
        return out, refs

    base, _ = names(project.get("dependencies", []))
    raw_extras = {extra: names(reqs) for extra, reqs in project.get("optional-dependencies", {}).items()}
    extras = {}
    for extra in raw_extras:
        seen, stack, dists = set(), [extra], set()
        while stack:
            current = stack.pop()
            if current in seen or current not in raw_extras:
                continue
            seen.add(current)
            dists |= raw_extras[current][0]
            stack.extend(raw_extras[current][1])
        extras[extra] = dists
    return base, extras


def requested_extras(path: Path = ROOT / "pyproject.toml", env: dict | None = None) -> dict[str, set[str]]:
    """Base distribution -> the extras its declaration requests (``httpx[socks]`` -> {"socks"}).

    A requested extra's requirements ship with the distribution: ``httpx`` loads
    ``socksio`` only when a SOCKS proxy is configured, so no static import reaches it.
    """
    project = tomllib.loads(path.read_text(encoding="utf-8-sig"))["project"]
    env = TARGET_ENV if env is None else env
    out: dict[str, set[str]] = {}
    for raw in project.get("dependencies", []):
        req = _req(raw)
        if req.extras and (req.marker is None or req.marker.evaluate(env)):
            out.setdefault(_norm(req.name), set()).update(req.extras)
    return out


def declared_anywhere(path: Path = ROOT / "pyproject.toml") -> set[str]:
    """Every distribution ``[project]`` declares (base + extras), markers NOT evaluated."""
    project = tomllib.loads(path.read_text(encoding="utf-8-sig"))["project"]
    raws = [*project.get("dependencies", []), *(r for reqs in project.get("optional-dependencies", {}).values()
                                                 for r in reqs)]
    return {_norm(_req(raw).name) for raw in raws} - {_norm(project["name"])}


def _lock(path: Path = ROOT / "uv.lock") -> dict[str, dict]:
    stat = path.stat()
    return dict(_parsed_lock(path, stat.st_mtime_ns, stat.st_size))


@functools.lru_cache(maxsize=4)
def _parsed_lock(path: Path, _mtime_ns: int, _size: int) -> dict[str, dict]:
    """uv.lock parsed once per file version: the parse is the largest cost of a closure
    walk, and the stat key re-reads a lock that changed."""
    return {_norm(p["name"]): p for p in tomllib.loads(path.read_text(encoding="utf-8-sig")).get("package", [])}


@functools.lru_cache(maxsize=4)
def _locked_versions(path: Path, _mtime_ns: int, _size: int) -> dict[str, frozenset[str]]:
    """Every version uv.lock pins per distribution (a forked resolution pins one name twice);
    the project's own editable / virtual entry is not a pin."""
    out: dict[str, set[str]] = {}
    for p in tomllib.loads(path.read_text(encoding="utf-8-sig")).get("package", []):
        if "version" in p and not {"editable", "virtual"} & set(p.get("source", {})):
            out.setdefault(_norm(p["name"]), set()).add(p["version"])
    return {name: frozenset(versions) for name, versions in out.items()}


def stale_against_lock(distributions, names, path: Path = ROOT / "uv.lock") -> list[str]:
    """Of ``distributions`` (``importlib.metadata`` objects) named in ``names`` (the closure the plan
    reached; a stale distribution it never reaches decides nothing), those whose version uv.lock does not pin, as
    ``"<name> <installed> (uv.lock <pins>)"`` — a site that lags the lock maps imports to the old
    requirements, and the plan then blames the pool for what the stale site asked for
    (RT-PHONE-BUILD-STALE-SEED-BLAMES-AN-EXTRA). A distribution uv.lock does not name is not judged."""
    stat = path.stat()
    pins = _locked_versions(path, stat.st_mtime_ns, stat.st_size)
    wanted, stale = {_norm(n) for n in names}, set()
    for dist in distributions:
        name, version = _norm(dist.metadata["Name"] or ""), dist.version
        if name in wanted and name in pins and version not in pins[name]:
            stale.add(f"{name} {version} (uv.lock {', '.join(sorted(pins[name]))})")
    return sorted(stale)


def _wheel_size(package: dict) -> int | None:
    """The Windows wheel's size from uv.lock (preferring cp314, cp312, abi3, then any)."""
    wheels = package.get("wheels", [])
    for tag in ("cp314-win_amd64", "cp312-win_amd64", "abi3-win_amd64", "none-win_amd64", "none-any"):
        for wheel in wheels:
            if wheel["url"].endswith(f"{tag}.whl") and wheel.get("size"):
                return wheel["size"]
    return None
