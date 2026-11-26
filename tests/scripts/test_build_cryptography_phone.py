"""Android cryptography 48.0.0, built against the interpreter's own OpenSSL: written the same way every time,
linked to ``libcrypto_python.so``, never moved off its pin.

Row ``RT-FU-THE-PHONE-ENGINE-DOWNLOAD-STAYS-UNDER-ITS-LIMIT-WITH-THE-LISTENERS-CRYPTOGRAPHY``.
``scripts/native/build_cryptography_phone.py`` builds with ``cargo ndk`` (run by hand, not here); these read
what it writes from given bytes, and the committed wheels it wrote.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.bundles import phone_wheels
from scripts.native import build_cryptography_phone as build

BUILD = {"rustc": "rustc 1.100.0", "target": "aarch64-linux-android"}
PACKAGE = {"cryptography/__init__.py": b"# pkg\n"}


def _wheel(library: bytes = b"\x7fELF lib", target: str = "android_arm64") -> bytes:
    return build.wheel_bytes(PACKAGE, library, b"Metadata-Version: 2.4\nName: cryptography\n", {"LICENSE": b"L"},
                             target, BUILD)


def test_the_same_inputs_give_the_same_wheel_bytes():
    assert _wheel() == _wheel()
    assert _wheel() != _wheel(b"\x7fELF lib2")


def test_the_wheel_holds_the_package_the_library_and_the_sdists_metadata(tmp_path):
    with zipfile.ZipFile(__import__("io").BytesIO(_wheel())) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    assert files[build.LIBRARY_IN_WHEEL] == b"\x7fELF lib"
    assert files["cryptography/__init__.py"] == b"# pkg\n"
    assert files["cryptography-48.0.0.dist-info/METADATA"].startswith(b"Metadata-Version: 2.4")
    assert b"Tag: cp314-cp314-android_24_arm64_v8a\n" in files["cryptography-48.0.0.dist-info/WHEEL"]
    assert build.wheel_name("android_x86_64") == "cryptography-48.0.0-cp314-cp314-android_24_x86_64.whl"


def test_a_library_that_does_not_link_the_interpreters_openssl_is_refused():
    """Mutation: drop the NEEDED check in ``library_problems`` -> red (a static-OpenSSL build passes)."""
    built = Path(__file__).parents[2] / phone_wheels.load()["wheels"]["cryptography"]["targets"]["android_arm64"]["path"]
    with zipfile.ZipFile(built) as archive:
        ours = archive.read(build.LIBRARY_IN_WHEEL)
    assert build.OPENSSL_SONAME in build.needed_libraries(ours)
    static = ours.replace(b"libcrypto_python.so\0", b"libcrypto_static.so\0")
    assert any(p.startswith("openssl_not_shared:") for p in build.library_problems(static, "lib.so", []))
    assert not any(p.startswith("openssl_not_shared:") for p in build.library_problems(ours, "lib.so", []))


def test_a_library_with_a_machine_path_is_refused():
    leaked = b"\x7fELF" + str(Path.home()).encode() + b"/.cargo/registry/src"
    with pytest.raises(build.BuildRefused):
        build.needed_libraries(leaked)  # not even an ELF
    built = Path(__file__).parents[2] / phone_wheels.load()["wheels"]["cryptography"]["targets"]["android_arm64"]["path"]
    with zipfile.ZipFile(built) as archive:
        ours = archive.read(build.LIBRARY_IN_WHEEL)
    assert any(p.startswith("machine_path:") for p in build.library_problems(ours + b"/home/someone/x", "l",
                                                                              ["/home/someone"]))


def test_a_rebuild_off_a_path_pin_is_refused():
    doc = {"wheels": {"cryptography": {"version": "48.0.0", "targets": {"android_arm64": {
        "path": "third_party/phone_wheels/cryptography/x.whl", "sha256": hashlib.sha256(b"committed").hexdigest()}}}}}
    assert build.pin_problem("android_arm64", b"rebuilt", doc).startswith("pin_mismatch: android_arm64")
    assert build.pin_problem("android_arm64", b"committed", doc) is None


def test_the_committed_wheels_are_what_the_script_names_and_pins():
    """Each Android pin is the script's wheel, built from the pinned sdist and interpreter, linking its OpenSSL."""
    for target in build.TARGETS:
        pin = phone_wheels.pins(target)[build.DISTRIBUTION]
        path = phone_wheels.ROOT / pin["path"]
        assert pin["version"] == build.VERSION and path.name == build.wheel_name(target)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pin["sha256"]
        with zipfile.ZipFile(path) as archive:
            recorded = json.loads(archive.read("cryptography-48.0.0.dist-info/BUILD.json"))
            library = archive.read(build.LIBRARY_IN_WHEEL)
        assert recorded["sdist_sha256"] == build.SDIST_SHA256
        assert recorded["interpreter_sha256"] == build.INTERPRETERS[target]
        assert build.library_problems(library, target, [str(Path.home())]) == []


_MINT_WITHOUT = r"""
import sys, tempfile
blocked = set(sys.argv[1].split(","))

class Absent:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in blocked:
            raise ModuleNotFoundError(f"left out on the phone: {name}", name=name)

sys.meta_path.insert(0, Absent())
from agent_runtime import gateway_tls
with tempfile.TemporaryDirectory() as store:
    minted = gateway_tls.ensure_certificate(store)
    read = gateway_tls.read_certificate(store)
print(type(minted).__name__, type(read).__name__, sorted(m for m in sys.modules if "cffi" in m))
"""


def test_the_listener_mints_and_reads_with_what_the_phone_leaves_out_of_cffi_absent():
    """The phone ships cffi's ``_cffi_backend`` only: its Python half is ``excluded_data`` and pycparser a
    placeholder. The real mint and PEM read run with exactly those imports unfindable.
    Mutation: add ``site-packages/_cffi_backend`` to the phone's excluded_data -> red (``_rust`` cannot load)."""
    import subprocess
    import sys

    from agent_runtime.bundle_profiles.manifest import load_profile

    pytest.importorskip("cryptography")
    manifest = load_profile("bundled-phone")
    left_out = {rel.split("/")[1] for rel in manifest.excluded_data if rel.startswith("site-packages/")
                and rel.count("/") == 1 and not any(ch in rel for ch in "*?[")}
    left_out |= {name.replace("-", "_") for name in manifest.placeholder_distributions}
    assert {"cffi", "pycparser"} <= left_out
    done = subprocess.run([sys.executable, "-c", _MINT_WITHOUT, ",".join(sorted(left_out))],
                          cwd=phone_wheels.ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.split() == ["GatewayCertificate", "GatewayCertificate", "['_cffi_backend']"]
