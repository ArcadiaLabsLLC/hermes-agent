"""The phone wheels uv.lock cannot hold (row RT-PHONE-PILLOW-ANDROID, owner RULED 2026-11-17).

``agent_runtime/bundle_profiles/phone_wheels.lock.json`` pins Flet's Android Pillow and the four image
libraries it links; ``scripts/bundles/phone_wheels.py`` feeds them to the pool, the plan and the gate.
These pin the file's own shape and the three decisions each reader takes from it.
"""

from __future__ import annotations

import re

import pytest

from scripts.bundle_profile_closure import _lock
from scripts.bundle_profile_gate import distribution_findings
from scripts.bundles import phone_wheels
from scripts.bundles.requirement_blocks import Block, requirement_blocks

ANDROID = {"android_arm64": "android_24_arm64_v8a", "android_x86_64": "android_24_x86_64"}
LIBRARIES = {"flet-libjpeg", "flet-libtiff", "flet-libfreetype", "flet-libwebp"}


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
    """Each pinned file is the wheel of that name and version for that target's ABI, with a sha256."""
    wheels = phone_wheels.load()["wheels"]
    assert set(wheels) == {"pillow", *LIBRARIES}
    for name, entry in wheels.items():
        assert set(entry["targets"]) == set(ANDROID), name
        for target, pin in entry["targets"].items():
            file = pin["url"].rsplit("/", 1)[1]
            assert pin["url"].startswith("https://pypi.flet.dev/"), file
            assert file.startswith(f"{name.replace('-', '_')}-{entry['version']}-"), file
            assert file.endswith(f"-{ANDROID[target]}.whl"), file
            assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]), file
    assert set(wheels["pillow"]["companions"]) == LIBRARIES


def test_pinned_pillow_is_the_version_uv_lock_pins():
    """One Pillow version on every target: the phone pin follows the desktop lock."""
    assert phone_wheels.version_problems(_lock()) == []


def test_a_pin_off_the_lock_version_is_named():
    assert phone_wheels.version_problems({"pillow": {"version": "12.3.0"}}, _doc()) == [
        "phone_wheel_version: pillow 13.0.0 is pinned for the phones, uv.lock pins 12.3.0: bump both together"]


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
