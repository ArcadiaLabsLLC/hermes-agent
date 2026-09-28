"""Known-vulnerability scan over a bundle's pinned distributions (plan D4 release gate).

Fork-owned (bundled desktop). Checks every pin against OSV (the database
pip-audit and uv read) and exits non-zero on a known vulnerability that no
waiver in :data:`WAIVERS` covers. What it scans:

* ``--bundle DIR`` (repeatable): the distributions a BUILT output records
  (``bundle-manifest.json`` for the core, ``engine-pack.json`` for a pack) —
  exactly what ships;
* otherwise the profile's exported pins (``uv export --frozen`` of the base
  dependencies plus the manifest's extras and every engine pack's extras, as
  :mod:`scripts.bundle_profile_package` pools them), every target's pins
  unless ``--target`` names one. That is a superset of what ships, which is
  the safe direction for a scan.

Where the advisories come from:

* ``--osv-db PATH`` — OFFLINE: OSV's PyPI export (``PyPI/all.zip`` from
  ``https://osv-vulnerabilities.storage.googleapis.com/PyPI/all.zip``, or a
  directory of its JSON records), matched locally;
* otherwise ONLINE: ``https://api.osv.dev/v1/querybatch``, then each hit's
  record. A scan that cannot reach its source exits 2 — it never passes.

A waiver is ``{"id", "distribution", "reason", "expires"}``; it covers a
finding whose id or alias equals ``id`` for that distribution until
``expires`` (``YYYY-MM-DD``, inclusive). An expired waiver covers nothing.

Exit: 0 clean (or every finding waived), 1 an unwaived vulnerability, 2 the
scan could not run. ``--json FILE`` writes the report.

Usage::

    python scripts/bundle_vuln_scan.py [--bundle DIR ...] [--target win32-x64] [--osv-db PyPI-all.zip] [--json out.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WAIVERS = ROOT / "agent_runtime" / "bundle_profiles" / "vulnerability-waivers.json"
OSV_API = "https://api.osv.dev/v1"
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# -- the pins -------------------------------------------------------------------------------------


def pins_from_requirements(text: str) -> dict[str, str]:
    """``name==version`` lines of a requirements export (markers ignored: every target's pin)."""
    pins: dict[str, str] = {}
    for line in text.splitlines():
        match = _PIN.match(line.strip())
        if match:
            pins[_norm(match.group(1))] = match.group(2)
    return pins


def pins_from_bundles(dirs: list[Path]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for directory in dirs:
        for name in ("bundle-manifest.json", "engine-pack.json"):
            record = directory / name
            if record.is_file():
                pins.update({_norm(k): v for k, v in json.loads(record.read_text(encoding="utf-8"))
                             ["distributions"].items()})
                break
        else:
            raise FileNotFoundError(f"{directory}: neither bundle-manifest.json nor engine-pack.json")
    return pins


def exported_pins(profile: str, target: str | None, uv: str = "uv") -> dict[str, str]:
    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_package import (evaluate_markers, export_requirements, locked_python_version,
                                                marker_env)

    manifest = load_profile(profile)
    pack_extras = tuple(e for extras in manifest.packaging_packs.values() for e in extras)
    text = export_requirements((*manifest.packaging_extras, *pack_extras), uv)
    if target:
        text = evaluate_markers(text, marker_env(target, locked_python_version()))
    return pins_from_requirements(text)


# -- matching an OSV record -----------------------------------------------------------------------


def _parse_version(text: str):
    from packaging.version import InvalidVersion, Version

    try:
        return Version(text)
    except InvalidVersion:
        return None


def affects(record: dict, name: str, version: str) -> bool:
    """OSV semantics: listed in ``versions``, or inside an ECOSYSTEM range
    (``introduced`` inclusive, ``fixed`` exclusive, ``last_affected`` inclusive)."""
    if record.get("withdrawn"):
        return False
    target = _parse_version(version)
    for affected in record.get("affected", []):
        package = affected.get("package", {})
        if package.get("ecosystem") != "PyPI" or _norm(package.get("name", "")) != name:
            continue
        if version in affected.get("versions", []):
            return True
        if target is None:
            continue
        for rng in affected.get("ranges", []):
            if rng.get("type") != "ECOSYSTEM":
                continue
            low = None
            for event in rng.get("events", []):
                if "introduced" in event:
                    low = _parse_version("0") if event["introduced"] == "0" else _parse_version(event["introduced"])
                elif low is not None and "fixed" in event:
                    fixed = _parse_version(event["fixed"])
                    if fixed is not None and low <= target < fixed:
                        return True
                    low = None
                elif low is not None and "last_affected" in event:
                    last = _parse_version(event["last_affected"])
                    if last is not None and low <= target <= last:
                        return True
                    low = None
            if low is not None and low <= target:
                return True
    return False


def _finding(record: dict, name: str, version: str) -> dict:
    fixed = sorted({e["fixed"] for a in record.get("affected", []) for r in a.get("ranges", [])
                    for e in r.get("events", []) if "fixed" in e
                    and _norm(a.get("package", {}).get("name", "")) == name})
    return {"distribution": name, "version": version, "id": record["id"],
            "aliases": sorted(record.get("aliases", [])), "summary": record.get("summary", ""),
            "fixed_in": fixed}


# -- sources ---------------------------------------------------------------------------------------


def _offline_records(db: Path):
    if db.is_dir():
        for path in sorted(db.glob("*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))
        return
    with zipfile.ZipFile(db) as archive:
        for member in archive.namelist():
            if member.endswith(".json"):
                yield json.loads(archive.read(member))


def scan_offline(pins: dict[str, str], db: Path) -> list[dict]:
    findings = []
    for record in _offline_records(db):
        names = {_norm(a.get("package", {}).get("name", "")) for a in record.get("affected", [])}
        for name in names & set(pins):
            if affects(record, name, pins[name]):
                findings.append(_finding(record, name, pins[name]))
    return findings


def _post(url: str, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read())


def scan_online(pins: dict[str, str]) -> list[dict]:
    names = sorted(pins)
    findings = []
    for start in range(0, len(names), 500):
        chunk = names[start:start + 500]
        body = {"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": pins[n]} for n in chunk]}
        for name, result in zip(chunk, _post(f"{OSV_API}/querybatch", body).get("results", [])):
            for hit in result.get("vulns", []):
                findings.append(_finding(_get(f"{OSV_API}/vulns/{hit['id']}"), name, pins[name]))
    return findings


# -- waivers ---------------------------------------------------------------------------------------


def load_waivers(path: Path = WAIVERS) -> list[dict]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("waivers", [])


def waiver_for(finding: dict, waivers: list[dict], today: dt.date) -> dict | None:
    ids = {finding["id"], *finding["aliases"]}
    for waiver in waivers:
        if waiver["id"] in ids and _norm(waiver["distribution"]) == finding["distribution"] \
                and dt.date.fromisoformat(waiver["expires"]) >= today:
            return waiver
    return None


def dedupe(findings: list[dict]) -> list[dict]:
    """One finding per advisory: OSV publishes a GHSA and its PYSEC alias as two records."""
    kept: list[dict] = []
    for finding in sorted(findings, key=lambda f: (f["distribution"], f["id"])):
        ids = {finding["id"], *finding["aliases"]}
        if not any(k["distribution"] == finding["distribution"] and ids & {k["id"], *k["aliases"]}
                   for k in kept):
            kept.append(finding)
    return kept


def judge(findings: list[dict], waivers: list[dict], today: dt.date) -> tuple[list[dict], list[dict]]:
    """-> (unwaived findings, waived findings with their waiver), one per advisory."""
    open_, waived = [], []
    for finding in dedupe(findings):
        waiver = waiver_for(finding, waivers, today)
        (waived if waiver else open_).append({**finding, **({"waiver": waiver} if waiver else {})})
    return open_, waived


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="bundled-desktop")
    parser.add_argument("--bundle", type=Path, action="append", default=[],
                        help="a built core or engine-pack directory (repeatable)")
    parser.add_argument("--target", help="evaluate the export's markers for one target (default: every pin)")
    parser.add_argument("--osv-db", type=Path, help="offline OSV PyPI export (all.zip or a directory)")
    parser.add_argument("--waivers", type=Path, default=WAIVERS)
    parser.add_argument("--json", type=Path, help="write the report here")
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args(argv)

    try:
        pins = pins_from_bundles(args.bundle) if args.bundle else exported_pins(args.profile, args.target, args.uv)
        findings = scan_offline(pins, args.osv_db) if args.osv_db else scan_online(pins)
    except Exception as exc:  # noqa: BLE001 — a scan that cannot run must fail, loudly
        print(f"SCAN FAILED ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2
    unwaived, waived = judge(findings, load_waivers(args.waivers), dt.date.today())
    report = {"schema": 1, "source": str(args.osv_db) if args.osv_db else OSV_API,
              "scanned": len(pins), "pins": dict(sorted(pins.items())),
              "unwaived": unwaived, "waived": waived}
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for finding in unwaived:
        print(f"VULNERABLE {finding['distribution']}=={finding['version']}: {finding['id']} "
              f"{' '.join(finding['aliases'])} fixed in {', '.join(finding['fixed_in']) or '(none)'} "
              f"— {finding['summary']}")
    for finding in waived:
        print(f"waived {finding['distribution']}=={finding['version']}: {finding['id']} "
              f"(until {finding['waiver']['expires']}: {finding['waiver']['reason']})")
    print(f"scanned {len(pins)} pins: {len(unwaived)} unwaived, {len(waived)} waived")
    return 1 if unwaived else 0


if __name__ == "__main__":
    raise SystemExit(main())
