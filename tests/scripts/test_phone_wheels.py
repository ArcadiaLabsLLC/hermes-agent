"""The phone wheels uv.lock cannot hold (row RT-PHONE-PILLOW-ANDROID, owner RULED 2026-11-17).

``agent_runtime/bundle_profiles/phone_wheels.lock.json`` pins Flet's Android Pillow and the four image
libraries it links; ``scripts/bundles/phone_wheels.py`` feeds them to the pool, the plan and the gate.
These pin the file's own shape and the three decisions each reader takes from it.
"""

from __future__ import annotations

import re

import pytest

from agent_runtime.bundle_profiles.manifest import load_profile
from scripts.bundle_profile_closure import _lock
from scripts.bundle_profile_gate import distribution_findings
from scripts.bundles import phone_wheels
from scripts.bundles.requirement_blocks import Block, requirement_blocks

ANDROID = {"android_arm64": "android_24_arm64_v8a", "android_x86_64": "android_24_x86_64"}
PHONES = {**ANDROID, "ios_arm64": "ios_13_0_arm64_iphoneos", "ios_arm64_simulator": "ios_13_0_arm64_iphonesimulator"}
#: The phone listener's certificate (owner RULED 2026-11-24): Flet's wheels on all four phone targets.
LISTENER_TLS = {"cryptography", "cffi"}
LIBRARIES = {"flet-libjpeg", "flet-libtiff", "flet-libfreetype", "flet-libwebp"}
MATCHER = "eternia-project-files-match"
NATIVE_MATCH = "agent_runtime.project_files.native_match"


def _doc(**pillow):
    return {"wheels": {
        "pillow": {"version": "13.0.0", "companions": ["flet-libjpeg"], **pillow,
                   "targets": {"android_arm64": {"url": "https://x/-/v1/pillow-13.0.0-2-cp314-cp314-android_24_arm64_v8a.whl",
                                                 "sha256": "a" * 64}}},
        "flet-libjpeg": {"version": "3.2.1",
                         "targets": {"android_arm64": {"url": "https://x/-/v2/flet_libjpeg-3.2.1-1-py3-none-android_24_arm64_v8a.whl",
                                                       "sha256": "b" * 64}}},
    }}


def test_every_pin_names_its_own_distribution_version_and_android_target():
    """Each pinned file is the wheel of that name and version for that target's ABI, with a sha256: Flet's by
    index URL, ripgrep's matcher and Android cryptography by their path in this repository (owner RULED 2026-11-21)."""
    wheels = phone_wheels.load()["wheels"]
    assert set(wheels) == {"pillow", *LIBRARIES, MATCHER, *LISTENER_TLS}
    for name, entry in wheels.items():
        assert set(entry["targets"]) == set(PHONES if name in LISTENER_TLS else ANDROID), name
        for target, pin in entry["targets"].items():
            file = phone_wheels.pinned_wheel(name, target)
            if name == MATCHER:
                assert set(pin) == {"path", "sha256"} and pin["path"].startswith("crates/project_files_match/dist/"), file
            elif name == "cryptography" and target in ANDROID:
                # Built here against the interpreter's OpenSSL (scripts/native/build_cryptography_phone.py).
                assert set(pin) == {"path", "sha256"} and pin["path"].startswith(
                    "third_party/phone_wheels/cryptography/"), file
            else:
                assert set(pin) == {"url", "sha256"} and pin["url"].startswith("https://pypi.flet.dev/"), file
            assert file.startswith(f"{name.replace('-', '_')}-{entry['version']}-"), file
            assert file.endswith(f"-{PHONES[target]}.whl"), file
            assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]), file
    assert set(wheels["pillow"]["companions"]) == LIBRARIES


def test_pinned_pillow_is_the_version_uv_lock_pins():
    """One Pillow version on every target: the phone pin follows the desktop lock."""
    assert phone_wheels.version_problems(_lock()) == []


def test_a_pin_off_the_lock_version_is_named():
    assert phone_wheels.version_problems({"pillow": {"version": "12.3.0"}}, _doc()) == [
        "phone_wheel_version: pillow 13.0.0 is pinned for the phones, uv.lock pins 12.3.0: bump both together"]


# ── the one phone-only exception: cryptography 48.0.0 (owner RULED 2026-11-24) ─────────────────────────────


def _crypto(version: str = "48.0.0", *targets: str) -> dict:
    return {"wheels": {"cryptography": {"version": version, "targets": {
        target: {"url": f"https://x/-/v/cryptography-{version}-10-cp314-cp314-{target}.whl", "sha256": "c" * 64}
        for target in (targets or ("android_arm64", "ios_arm64"))}}}}


def test_cryptography_48_is_pinned_for_the_phones_by_the_one_named_exception():
    """The lock's 50.0.2 stays the desktop's; the phones' 48.0.0 passes only under its named entry, which cites the
    ruling and the release row that removes it. Positive control: the same pin with the entry gone is named."""
    exception = phone_wheels.PHONE_ONLY_VERSION_EXCEPTIONS
    assert set(exception) == {"cryptography"}
    assert exception["cryptography"]["version"] == phone_wheels.load()["wheels"]["cryptography"]["version"] == "48.0.0"
    assert exception["cryptography"]["row"] == "RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR"
    assert _lock()["cryptography"]["version"] == "50.0.2"
    assert phone_wheels.version_problems({"cryptography": {"version": "50.0.2"}}, _crypto()) == []
    saved = exception.pop("cryptography")
    try:
        assert phone_wheels.version_problems({"cryptography": {"version": "50.0.2"}}, _crypto()) == [
            "phone_wheel_version: cryptography 48.0.0 is pinned for the phones, uv.lock pins 50.0.2: bump both together"]
    finally:
        exception["cryptography"] = saved


def test_the_desktop_floor_still_refuses_cryptography_48():
    """The exception never lowers the desktop: a lock at 48.0.0 (or anything under 50.0.0) is refused even though
    it then equals the phone pin. Killing mutation: drop the floor test in ``_excepted`` (seen red 2026-11-24)."""
    assert phone_wheels.version_problems({"cryptography": {"version": "48.0.0"}}, _crypto()) == [
        "phone_wheel_version: cryptography 48.0.0 in uv.lock is under the desktop floor 50.0.0; the phone-only "
        "exception (RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR) never lowers it"]
    assert phone_wheels.version_problems({"cryptography": {"version": "49.0.0"}}, _crypto())


def test_the_exception_covers_phone_targets_only():
    """48.0.0 pinned for a desktop target is refused. Killing mutation: drop the desktop-target test (seen red)."""
    assert phone_wheels.version_problems({"cryptography": {"version": "50.0.2"}}, _crypto("48.0.0", "android_arm64",
                                                                                         "linux-x64")) == [
        "phone_wheel_version: cryptography 48.0.0 is excepted on phones only, not on linux-x64 "
        "(RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR)"]


def test_another_cryptography_version_is_not_excepted():
    """One version, not a range: 47.0.0 on the phones is the ordinary mismatch."""
    assert phone_wheels.version_problems({"cryptography": {"version": "50.0.2"}}, _crypto("47.0.0")) == [
        "phone_wheel_version: cryptography 47.0.0 is pinned for the phones, uv.lock pins 50.0.2: bump both together"]


def test_the_pool_takes_the_pin_in_place_of_the_lock_block_and_adds_its_companions():
    export = requirement_blocks("pillow==13.0.0 ; python_full_version >= '3.14' \\\n"
                                "    --hash=sha256:" + "c" * 64 + "\n"
                                "idna==3.11 \\\n    --hash=sha256:" + "d" * 64 + "\n")
    blocks = phone_wheels.pinned_blocks(export, "android_arm64", _doc())
    assert [b.name for b in blocks] == ["pillow", "idna", "flet-libjpeg"]
    assert blocks[0] == Block("pillow", "pillow @ https://x/-/v1/pillow-13.0.0-2-cp314-cp314-android_24_arm64_v8a.whl",
                              "", ("    --hash=sha256:" + "a" * 64,))
    assert blocks[1] == export[1]
    assert blocks[2].hashes == ("    --hash=sha256:" + "b" * 64,)


def test_another_target_keeps_the_lock_blocks():
    export = requirement_blocks("pillow==13.0.0 \\\n    --hash=sha256:" + "c" * 64 + "\n")
    assert phone_wheels.pinned_blocks(export, "ios_arm64", _doc()) == export


def test_companions_ship_only_where_their_distribution_is_pinned():
    assert phone_wheels.with_companions({"pillow", "idna"}, "android_arm64", _doc()) == {"pillow", "idna", "flet-libjpeg"}
    assert phone_wheels.with_companions({"pillow"}, "ios_arm64", _doc()) == {"pillow"}
    assert phone_wheels.with_companions({"idna"}, "android_arm64", _doc()) == {"idna"}


def test_a_companion_with_no_pin_on_the_target_is_refused():
    doc = _doc(companions=["flet-libjpeg", "flet-libtiff"])
    with pytest.raises(ValueError, match=r"companions not pinned on android_arm64: \['flet-libtiff'\]"):
        phone_wheels.with_companions({"pillow"}, "android_arm64", doc)


def test_the_gate_judges_a_pinned_phone_wheel_by_its_own_file():
    """uv.lock holds no flet-lib* entry and no Android Pillow wheel: the pin is what ships there."""
    shipped = {"pillow", *LIBRARIES}
    admitted = {"pillow", *LIBRARIES}
    assert distribution_findings(shipped, {}, admitted, "android_arm64") == []
    findings = distribution_findings(shipped, {}, admitted - {"flet-libtiff"}, "android_x86_64")
    assert findings == [{"kind": "native", "subject": "flet-libtiff"}]


def _matcher_doc():
    doc = _doc()
    doc["wheels"][MATCHER] = {"version": "1.0.0", "loaded_by": NATIVE_MATCH, "targets": {"android_arm64": {
        "path": "crates/project_files_match/dist/eternia_project_files_match-1.0.0-py3-none-android_24_arm64_v8a.whl",
        "sha256": "e" * 64}}}
    return doc


def test_a_repo_path_pin_installs_from_its_file_in_this_checkout():
    export = requirement_blocks("idna==3.11 \\\n    --hash=sha256:" + "d" * 64 + "\n")
    block, = [b for b in phone_wheels.pinned_blocks(export, "android_arm64", _matcher_doc()) if b.name == MATCHER]
    wheel = phone_wheels.ROOT / "crates/project_files_match/dist/eternia_project_files_match-1.0.0-py3-none-android_24_arm64_v8a.whl"
    assert block == Block(MATCHER, f"{MATCHER} @ {wheel.as_uri()}", "", ("    --hash=sha256:" + "e" * 64,))
    assert phone_wheels.pinned_wheel(MATCHER, "android_arm64", _matcher_doc()) == wheel.name


def test_a_first_party_library_ships_only_with_the_module_that_loads_it():
    """Mutation: drop the ``modules`` test in ``loaded_by`` -> red (it ships without the file tools)."""
    doc = _matcher_doc()
    assert phone_wheels.loaded_by({NATIVE_MATCH, "x"}, "android_arm64", doc) == {MATCHER}
    assert phone_wheels.loaded_by({"x"}, "android_arm64", doc) == set()
    assert phone_wheels.loaded_by(None, "android_arm64", doc) == {MATCHER}  # the pool installs it
    assert phone_wheels.loaded_by({NATIVE_MATCH}, "ios_arm64", doc) == set()  # not pinned there


def test_the_module_named_as_the_loader_really_loads_the_locator():
    """The pin's ``loaded_by`` is the binding, and the binding imports the wheel's locator."""
    entry = phone_wheels.load()["wheels"][MATCHER]
    source = (phone_wheels.ROOT / (entry["loaded_by"].replace(".", "/") + ".py")).read_text(encoding="utf-8")
    assert "from eternia_project_files_match import LIBRARY" in source


def test_the_gate_judges_the_pinned_library_its_kept_module_loads(monkeypatch):
    """Mutation: the gate judges ``shipped`` alone (no ``judged_distributions``) -> red: the unadmitted
    library would ship unjudged."""
    from scripts import bundle_profile_gate as gate

    monkeypatch.setattr(phone_wheels, "load", lambda path=None: _matcher_doc())
    judged = gate.judged_distributions({"pillow", "idna"}, {NATIVE_MATCH}, "android_arm64")
    assert judged == {"pillow", "idna", "flet-libjpeg", MATCHER}
    assert gate.judged_distributions({"idna"}, set(), "android_arm64") == {"idna"}
    assert distribution_findings(judged, {"idna": {"wheels": [{"url": "idna-3.11-py3-none-any.whl"}]}},
                                 {"pillow", "flet-libjpeg"}, "android_arm64") == [{"kind": "native", "subject": MATCHER}]
    assert MATCHER in {gate._norm(n) for n in load_profile("bundled-phone").admitted_native}


def test_the_pool_reads_alignment_on_android_only(tmp_path):
    """Mutation: read every target -> red (an iOS pool's Mach-O library is refused as not ELF)."""
    from scripts.bundle_profile_package import pool_alignment_problems

    (tmp_path / "libx.so").write_bytes(b"\xcf\xfa\xed\xfe Mach-O")
    assert pool_alignment_problems(tmp_path, "ios_arm64") == []
    assert pool_alignment_problems(tmp_path, "android_arm64") == [
        "page_alignment: libx.so cannot be read as ELF (not an ELF file)"]
