"""The library wheel of ripgrep's matcher: written the same way every time, never moved off its pin.

Row ``RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID``. ``scripts/native/build_project_files_match.py`` builds with
``cargo ndk`` (run by hand, not here); these read what it writes from given library bytes, and the
committed wheels it wrote.
"""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.bundles import phone_wheels
from scripts.native import build_project_files_match as build

BUILD = {"rustc": "rustc 1.100.0", "target": "x86_64-linux-android"}


def _doc(sha: str) -> dict:
    return {"wheels": {build.DISTRIBUTION: {"version": "1.0.0", "targets": {"android_x86_64": {
        "path": "crates/project_files_match/dist/x.whl", "sha256": sha}}}}}


def test_the_same_library_gives_the_same_wheel_bytes():
    one = build.wheel_bytes(b"\x7fELF lib", "1.0.0", "android_x86_64", BUILD)
    assert one == build.wheel_bytes(b"\x7fELF lib", "1.0.0", "android_x86_64", BUILD)
    assert one != build.wheel_bytes(b"\x7fELF lib2", "1.0.0", "android_x86_64", BUILD)


def test_the_wheel_holds_the_library_its_locator_and_a_true_record(tmp_path):
    wheel = tmp_path / build.wheel_name("1.0.0", "android_arm64")
    assert wheel.name == "eternia_project_files_match-1.0.0-py3-none-android_24_arm64_v8a.whl"
    wheel.write_bytes(build.wheel_bytes(b"\x7fELF lib", "1.0.0", "android_arm64", BUILD))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        files = {name: archive.read(name) for name in names}
        assert {info.date_time for info in archive.infolist()} == {build.ZIP_TIME}
    assert files["eternia_project_files_match/libproject_files_match.so"] == b"\x7fELF lib"
    assert b"Tag: py3-none-android_24_arm64_v8a\n" in files["eternia_project_files_match-1.0.0.dist-info/WHEEL"]
    for line in files["eternia_project_files_match-1.0.0.dist-info/RECORD"].decode().splitlines()[:-1]:
        name, digest, size = line.rsplit(",", 2)
        expected = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).rstrip(b"=").decode()
        assert (digest, int(size)) == (f"sha256={expected}", len(files[name])), name
    namespace: dict = {"__file__": "/site/eternia_project_files_match/__init__.py"}
    exec(files["eternia_project_files_match/__init__.py"].decode(), namespace)  # noqa: S102 — our own locator
    assert namespace["LIBRARY"] == "/site/eternia_project_files_match/libproject_files_match.so"


def test_a_rebuild_off_the_pin_is_refused_and_the_wheel_is_kept(tmp_path):
    """Mutation: ``pin_problem`` returns None -> red (the differing wheel overwrites the committed one)."""
    kept = tmp_path / build.wheel_name("1.0.0", "android_x86_64")
    kept.write_bytes(b"committed")
    rebuilt = b"rebuilt"
    with pytest.raises(build.BuildRefused, match="pin_mismatch: android_x86_64 rebuilt as sha256 .* never re-pin"):
        build.write_wheel("android_x86_64", rebuilt, "1.0.0", tmp_path, _doc(hashlib.sha256(b"committed").hexdigest()))
    assert kept.read_bytes() == b"committed"
    written = build.write_wheel("android_x86_64", rebuilt, "1.0.0", tmp_path, _doc(hashlib.sha256(rebuilt).hexdigest()))
    assert written.read_bytes() == rebuilt


def test_a_library_with_a_machine_path_is_refused():
    leaked = b"\x7fELF" + str(Path.home()).encode() + b"/.cargo/registry/src"
    assert any(p.startswith("machine_path:") for p in build.library_problems(leaked, "lib.so"))


def test_the_committed_wheels_are_what_the_script_names_and_pins():
    """Each pinned target's committed wheel carries the script's name, the crate's version and the locator."""
    pins = {t: phone_wheels.pins(t)[build.DISTRIBUTION] for t in build.TARGETS}
    for target, pin in pins.items():
        assert pin["version"] == build.crate_version()
        path = phone_wheels.ROOT / pin["path"]
        assert path.name == build.wheel_name(pin["version"], target)
        with zipfile.ZipFile(path) as archive:
            assert "eternia_project_files_match/__init__.py" in archive.namelist()
