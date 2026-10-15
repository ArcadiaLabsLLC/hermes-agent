"""The bundle's vulnerability gate (plan D4): OSV range semantics, waivers, and the exit code."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from scripts.bundle_vuln_scan import affects, dedupe, judge, main

TODAY = dt.date(2026, 9, 28)


def _record(vid="GHSA-1", name="lib", events=(("introduced", "0"), ("fixed", "2.0")), versions=(),
            aliases=("CVE-1",), **extra):
    return {"id": vid, "aliases": list(aliases), "summary": "s",
            "affected": [{"package": {"ecosystem": "PyPI", "name": name}, "versions": list(versions),
                          "ranges": [{"type": "ECOSYSTEM", "events": [{k: v} for k, v in events]}]}],
            **extra}


def test_osv_ranges_introduced_inclusive_fixed_exclusive_last_affected_inclusive():
    assert affects(_record(), "lib", "1.9")
    assert not affects(_record(), "lib", "2.0")
    ranged = _record(events=(("introduced", "1.2"), ("last_affected", "1.4")))
    assert [affects(ranged, "lib", v) for v in ("1.1", "1.2", "1.4", "1.5")] == [False, True, True, False]
    assert affects(_record(events=(("introduced", "3.0"),)), "lib", "9.0")  # never fixed
    assert affects(_record(events=(), versions=("0.5",)), "lib", "0.5")
    assert not affects(_record(), "other", "1.0")
    assert not affects(_record(withdrawn="2026-01-01T00:00:00Z"), "lib", "1.0")


def _finding(vid="GHSA-1", dist="lib", aliases=("CVE-1",)):
    return {"distribution": dist, "version": "1.0", "id": vid, "aliases": list(aliases), "summary": "",
            "fixed_in": ["2.0"]}


def test_a_waiver_covers_its_advisory_by_id_or_alias_for_its_distribution_until_it_expires():
    waiver = {"id": "CVE-1", "distribution": "lib", "reason": "r", "expires": "2026-09-28"}
    assert judge([_finding()], [waiver], TODAY)[0] == []
    assert judge([_finding()], [waiver], TODAY + dt.timedelta(days=1))[0] != []  # expired
    assert judge([_finding(dist="other")], [waiver], TODAY)[0] != []
    assert judge([_finding()], [], TODAY)[0] != []


def test_an_advisory_published_twice_under_aliases_is_one_finding():
    twins = [_finding("GHSA-1", aliases=("PYSEC-1",)), _finding("PYSEC-1", aliases=("GHSA-1",))]
    assert len(dedupe(twins)) == 1
    assert len(dedupe([*twins, _finding("GHSA-2", aliases=())])) == 2


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "core"
    bundle.mkdir()
    (bundle / "bundle-manifest.json").write_text(json.dumps({"distributions": {"lib": "1.0"}}), encoding="utf-8")
    return bundle


def test_the_gate_exits_1_on_an_unwaived_vulnerability_and_0_once_it_is_waived(tmp_path: Path):
    db = tmp_path / "osv"
    db.mkdir()
    (db / "GHSA-1.json").write_text(json.dumps(_record()), encoding="utf-8")
    waivers = tmp_path / "waivers.json"
    waivers.write_text(json.dumps({"waivers": []}), encoding="utf-8")
    args = ["--bundle", str(_bundle(tmp_path)), "--osv-db", str(db), "--waivers", str(waivers)]
    assert main(args) == 1
    waivers.write_text(json.dumps({"waivers": [{"id": "GHSA-1", "distribution": "lib", "reason": "r",
                                                "expires": "2999-01-01"}]}), encoding="utf-8")
    assert main(args) == 0


def test_a_scan_that_cannot_read_its_source_fails_with_2(tmp_path: Path):
    assert main(["--bundle", str(_bundle(tmp_path)), "--osv-db", str(tmp_path / "missing.zip")]) == 2
