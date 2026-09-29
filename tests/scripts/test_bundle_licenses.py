"""Licences + SBOM per bundle output (plan D4): what is flagged for review, and that the
record names exactly what the output ships with every licence file it cites present."""

from __future__ import annotations

import hashlib
import json
from email.parser import HeaderParser
from pathlib import Path

import pytest

from scripts.bundle_licenses import (
    LICENCE_TEXTS,
    installed_wheel,
    licence_expression,
    licence_overrides,
    licence_problems,
    lock_wheels,
    place_override,
    review_reasons,
    write_licence_records,
)


def test_copyleft_non_commercial_and_unknown_licences_are_flagged_permissive_ones_are_not():
    assert review_reasons("MIT") == []
    assert review_reasons("Apache-2.0 AND BSD-3-Clause") == []
    assert review_reasons("GPL-3.0-or-later") == ["GPL-family licence"]
    assert review_reasons("LGPL-2.1-only") == ["LGPL-family licence"]
    assert review_reasons("AGPL-3.0-only") == ["AGPL-family licence"]
    assert review_reasons("CC-BY-NC-4.0") == ["non-commercial licence"]
    assert review_reasons("UNKNOWN")[0].startswith("unknown licence")
    assert review_reasons("")[0].startswith("unknown licence")


def test_a_copyleft_component_compiled_into_a_permissive_wheel_is_flagged():
    embedded = [{"name": "espeak-ng", "licence": "GPL-3.0-or-later"}]
    assert review_reasons("MIT", embedded) == ["embedded espeak-ng: GPL-family licence"]


def _meta(text: str):
    return HeaderParser().parsestr(text)


def test_the_licence_expression_prefers_pep639_then_the_field_then_classifiers():
    assert licence_expression(_meta("Name: a\nLicense-Expression: MIT\nLicense: BSD\n")) == "MIT"
    assert licence_expression(_meta("Name: a\nLicense: BSD-3-Clause\n")) == "BSD-3-Clause"
    classified = "Name: a\nClassifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)\n"
    assert licence_expression(_meta(classified)) == "GPL-3.0-only"
    assert licence_expression(_meta("Name: a\n")) == "UNKNOWN"


def _wheel(url: str, digest: str) -> dict:
    return {"url": url, "hash": f"sha256:{digest}"}


def test_the_wheel_is_the_lock_entry_whose_tags_equal_the_installed_ones(tmp_path: Path):
    info = tmp_path / "x-1.0.dist-info"
    info.mkdir()
    (info / "WHEEL").write_text("Wheel-Version: 1.0\nTag: cp314-cp314-win_amd64\n", encoding="utf-8")
    wheels = {("x", "1.0"): [_wheel("https://h/x-1.0-cp314-cp314-manylinux_2_28_x86_64.whl", "aa"),
                             _wheel("https://h/x-1.0-cp314-cp314-win_amd64.whl", "bb")]}
    assert installed_wheel(info, "x", "1.0", wheels)["hash"] == "sha256:bb"
    (info / "WHEEL").write_text("Wheel-Version: 1.0\nTag: cp314-cp314-macosx_11_0_arm64\n", encoding="utf-8")
    assert installed_wheel(info, "x", "1.0", wheels) is None


def _install(site: Path, name: str, licence: str, with_file: bool = True) -> None:
    info = site / f"{name}-1.0.dist-info"
    (info / "licenses").mkdir(parents=True)
    header = f"Metadata-Version: 2.4\nName: {name}\nVersion: 1.0\nLicense-Expression: {licence}\n"
    if with_file:
        header += "License-File: LICENSE\n"
        (info / "licenses" / "LICENSE").write_text("text", encoding="utf-8")
    (info / "METADATA").write_text(header, encoding="utf-8")
    (info / "WHEEL").write_text("Wheel-Version: 1.0\nTag: py3-none-any\n", encoding="utf-8")


def test_a_pack_record_names_its_distributions_and_its_licence_files_exist(tmp_path: Path):
    site = tmp_path / "site-packages"
    _install(site, "piper-tts", "MIT")
    _install(site, "numpy", "BSD-3-Clause")
    wheels = {("piper-tts", "1.0"): [_wheel("https://h/piper_tts-1.0-py3-none-any.whl", "cc")]}
    record = write_licence_records(tmp_path, "speech", {"piper-tts", "numpy"}, "win32-x64", "c0ffee",
                                   core=False, wheels=wheels)
    rows = {r["distribution"]: r for r in record["components"]}
    assert rows["piper-tts"]["wheel_sha256"] == "cc"
    assert rows["piper-tts"]["licence_files"] == ["site-packages/piper-tts-1.0.dist-info/licenses/LICENSE"]
    assert record["review_required"] == ["piper-tts"]  # espeak-ng, compiled in
    assert licence_problems(tmp_path, {"piper-tts", "numpy"}) == []
    bom = json.loads((tmp_path / "sbom.cdx.json").read_text(encoding="utf-8"))
    assert {c["purl"] for c in bom["components"]} == {"pkg:pypi/numpy@1.0", "pkg:pypi/piper-tts@1.0"}

    # The same output, one fact changed each time: the verify must see it.
    assert licence_problems(tmp_path, {"piper-tts", "numpy", "onnxruntime"}) == [
        "licenses.json does not list a shipped distribution: onnxruntime"]
    (site / "numpy-1.0.dist-info" / "licenses" / "LICENSE").unlink()
    assert licence_problems(tmp_path, {"piper-tts", "numpy"}) == [
        "licenses.json: licence file of numpy is not in the output: "
        "site-packages/numpy-1.0.dist-info/licenses/LICENSE"]


def test_a_distribution_without_licence_text_is_flagged(tmp_path: Path):
    _install(tmp_path / "site-packages", "bare", "MIT", with_file=False)
    record = write_licence_records(tmp_path, "p", {"bare"}, "win32-x64", "c0ffee", core=False, wheels={})
    assert record["components"][0]["review_reasons"] == ["no licence text in the output"]


def test_the_core_record_carries_the_interpreter_and_the_first_party_app(tmp_path: Path):
    (tmp_path / "site-packages").mkdir()
    (tmp_path / "app").mkdir()
    record = write_licence_records(tmp_path, "core", set(), "win32-x64", "c0ffee" * 7, core=True, wheels={})
    kinds = {r["kind"]: r for r in record["components"]}
    assert kinds["interpreter"]["wheel_sha256"]  # the lock's archive SHA-256
    assert kinds["interpreter"]["licence"] == "PSF-2.0"
    assert kinds["first-party"]["licence"] == "MIT"
    assert licence_problems(tmp_path, set()) == []


# -- vetted licence texts for wheels that ship none ----------------------------------------------


def _bare(site: Path, name: str, version: str, header: str = "") -> None:
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n{header}",
                                   encoding="utf-8")
    (info / "WHEEL").write_text("Wheel-Version: 1.0\nTag: py3-none-any\n", encoding="utf-8")


def _override(root: Path, name: str, version: str, text: bytes = b"Apache text\n") -> dict:
    (root / name / version).mkdir(parents=True)
    (root / name / version / "LICENSE").write_bytes(text)
    return {"version": version, "licence": "Apache-2.0",
            "files": {"LICENSE": hashlib.sha256(text).hexdigest()},
            "source_url": "https://h/x/LICENSE", "tag": f"v{version}", "commit": "ab" * 20}


def test_a_wheel_without_licence_text_gets_its_override_only_at_the_vetted_version(tmp_path: Path):
    texts, out = tmp_path / "texts", tmp_path / "out"
    _bare(out / "site-packages", "bare", "1.0")
    overrides = {"bare": _override(texts, "bare", "1.0")}
    record = write_licence_records(out, "p", {"bare"}, "win32-x64", "c0ffee", core=False, wheels={},
                                   overrides=overrides, override_root=texts)
    row = record["components"][0]
    assert row["licence_files"] == ["licence-texts/bare/1.0/LICENSE"]
    assert (out / "licence-texts/bare/1.0/LICENSE").read_bytes() == b"Apache text\n"
    assert row["licence"] == "Apache-2.0"  # the wheel's metadata named none
    assert row["licence_text_override"]["tag"] == "v1.0"
    assert (row["review"], record["review_required"]) == (False, [])
    assert licence_problems(out, {"bare"}, overrides) == []

    # The same wheel, bumped: the override is stale, so it is not applied and the verify fails.
    stale = tmp_path / "stale"
    _bare(stale / "site-packages", "bare", "1.1")
    record = write_licence_records(stale, "p", {"bare"}, "win32-x64", "c0ffee", core=False, wheels={},
                                   overrides=overrides, override_root=texts)
    row = record["components"][0]
    assert row["licence_files"] == [] and not (stale / "licence-texts").exists()
    assert "no licence text in the output" in row["review_reasons"]
    assert licence_problems(stale, {"bare"}, overrides) == [
        "licence-text override of bare is vetted at 1.0, the output ships 1.1: re-vet it "
        "(agent_runtime/bundle_profiles/licence-texts)"]


def test_an_override_the_wheel_metadata_contradicts_stays_in_review(tmp_path: Path):
    texts, out = tmp_path / "texts", tmp_path / "out"
    _bare(out / "site-packages", "bare", "1.0", "License: MIT\n")
    overrides = {"bare": _override(texts, "bare", "1.0")}
    row = write_licence_records(out, "p", {"bare"}, "win32-x64", "c0ffee", core=False, wheels={},
                                overrides=overrides, override_root=texts)["components"][0]
    assert row["review_reasons"] == ["vetted licence text is Apache-2.0; the wheel metadata says MIT"]
    # Positive control: a spelling of the same licence is not a contradiction.
    _bare(tmp_path / "o2" / "site-packages", "bare", "1.0", "License: Apache 2.0\n")
    row = write_licence_records(tmp_path / "o2", "p", {"bare"}, "win32-x64", "c0ffee", core=False,
                                wheels={}, overrides=overrides, override_root=texts)["components"][0]
    assert row["review"] is False


def test_a_vetted_text_whose_bytes_changed_is_refused(tmp_path: Path):
    texts = tmp_path / "texts"
    override = _override(texts, "bare", "1.0")
    (texts / "bare" / "1.0" / "LICENSE").write_bytes(b"edited\n")
    with pytest.raises(ValueError, match="changed"):
        place_override(tmp_path / "out", "bare", override, texts)


def test_every_vetted_override_matches_its_text_and_the_locked_version():
    overrides = licence_overrides()
    assert set(overrides) >= {"fal-client", "firecrawl-anydoc", "ctranslate2", "flatbuffers", "tokenizers"}
    locked = {name: version for name, version in lock_wheels()}
    for name, override in overrides.items():
        assert locked.get(name) == override["version"], f"{name}: uv.lock pins {locked.get(name)}"
        for filename, digest in override["files"].items():
            text = (LICENCE_TEXTS / name / override["version"] / filename).read_bytes()
            assert hashlib.sha256(text).hexdigest() == digest, f"{name}/{filename}"
        assert override["commit"] and override["tag"] and override["source_url"].startswith("https://")
