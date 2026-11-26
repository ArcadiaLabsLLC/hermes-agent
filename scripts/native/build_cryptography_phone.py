"""Build ``cryptography`` 48.0.0 for an Android phone against the interpreter's own OpenSSL.

Fork-owned (row ``RT-FU-THE-PHONE-ENGINE-DOWNLOAD-STAYS-UNDER-ITS-LIMIT-WITH-THE-LISTENERS-CRYPTOGRAPHY``).
Flet's prebuilt phone wheel links a second, static OpenSSL (3.0.20) into ``_rust.abi3.so``; the
phone already ships CPython's ``libcrypto_python.so`` / ``libssl_python.so`` (OpenSSL 3.5.x) for
``ssl`` and ``hashlib``. This build links the same Rust extension against those, so the phone
carries one OpenSSL. The version stays 48.0.0 (owner RULED 2026-11-24: "for now use 48"; the
release row ``RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR``
moves it with this same script). Like ``scripts/native/build_project_files_match.py``, the phone
packager builds nothing from source: this script is run by hand, its wheels are committed under
``third_party/phone_wheels/cryptography/`` and pinned by repo-relative path and sha256 in
``agent_runtime/bundle_profiles/phone_wheels.lock.json``.

    python scripts/native/build_cryptography_phone.py --sdist cryptography-48.0.0.tar.gz \\
        --interpreter android_arm64=python-3.14.9-aarch64-linux-android.tar.gz \\
        --interpreter android_x86_64=python-3.14.9-x86_64-linux-android.tar.gz

* **The inputs are pinned here.** The sdist is PyPI's (sha256 :data:`SDIST_SHA256`); each
  interpreter is python.org's Android package, the one Eternia's ``python-runtime.lock.json`` pins
  (sha256 :data:`INTERPRETERS`). A file with another hash is refused. Run under a CPython 3.14
  that has ``cffi`` and ``setuptools`` (``cryptography``'s ``_cffi_src/build_openssl.py`` runs
  on the host).
* **The build.** ``cargo ndk -t <abi> --platform 24 build --release --locked -p cryptography-rust``
  in the sdist, under the rustup ``--toolchain`` (refused unless ``rustc -V`` is :data:`RUST_TOOLCHAIN`).
  ``openssl-sys`` is pointed at the interpreter's ``prefix`` with ``OPENSSL_LIBS=ssl_python:
  crypto_python`` and no static or vendored OpenSSL; ``pyo3`` at its ``prefix/lib`` (it links
  ``libpython3.14.so``, as every Android extension must). Symbols are stripped. Paths are remapped
  and the library is refused when a machine path is still in it, when it does not NEED
  ``libcrypto_python.so``, or when a ``LOAD`` segment is aligned below 16 KB.
* **The wheel.** The sdist's ``src/cryptography`` and the library at
  ``cryptography/hazmat/bindings/_rust.abi3.so``, tagged ``cp314-cp314-android_24_<abi>`` like
  Flet's; its METADATA is the sdist's ``PKG-INFO`` (so ``Requires-Dist: cffi`` stays: the
  extension's cffi-generated init imports ``_cffi_backend``). Written deterministically.
  ``BUILD.json`` records the toolchain, the NDK, the API level and every input's sha256.
* **The pin is never moved here.** As in ``build_project_files_match.py``: a target with a path
  pin must rebuild to the pinned sha256 or the run is refused and the committed wheel kept.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bundles import elf_alignment
from scripts.bundles import phone_wheels

DIST = ROOT / "third_party" / "phone_wheels" / "cryptography"
DISTRIBUTION = "cryptography"
VERSION = "48.0.0"
#: PyPI's sdist of cryptography 48.0.0 (read from pypi.org/pypi/cryptography/48.0.0/json, 2026-11-26).
SDIST_SHA256 = "5c3932f4436d1cccb036cb0eaef46e6e2db91035166f1ad6505c3c9d5a635920"
#: python.org's CPython 3.14.9 Android packages, as Eternia's
#: ``packages/agents/eternia_hermes_embedded/python-runtime.lock.json`` pins them.
INTERPRETERS = {
    "android_arm64": "e2601ffefb36bd34f49e8743d7ba3dad793bb4478fe879d45773311868b85cc5",
    "android_x86_64": "af218190e6ad0fbce98e46c17ea495383db045488298cfdeb081278a86941170",
}
#: The rustc the wheels are built with (the toolchain project_files_match pins); ``--toolchain`` names the
#: rustup toolchain that answers it (this box installs 1.100.0 as ``stable``).
RUST_TOOLCHAIN = "1.100.0"
API_LEVEL = 24
PYTHON_VERSION = "3.14"
LIBRARY_IN_WHEEL = "cryptography/hazmat/bindings/_rust.abi3.so"
#: The interpreter's OpenSSL the extension must link (its SONAME in the Android package).
OPENSSL_SONAME = "libcrypto_python.so"
#: phone target -> (cargo-ndk ABI, Rust target triple, wheel platform tag)
TARGETS = {
    "android_arm64": ("arm64-v8a", "aarch64-linux-android", f"android_{API_LEVEL}_arm64_v8a"),
    "android_x86_64": ("x86_64", "x86_64-linux-android", f"android_{API_LEVEL}_x86_64"),
}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class BuildRefused(RuntimeError):
    """The build or its wheel failed a rule above; the message says which."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_input(path: Path, expected: str, label: str) -> None:
    found = sha256_file(path)
    if found != expected:
        raise BuildRefused(f"input_hash: {label} {path.name} is sha256 {found}, the pin is {expected}")


def wheel_name(target: str) -> str:
    return f"{DISTRIBUTION}-{VERSION}-cp314-cp314-{TARGETS[target][2]}.whl"


def _record_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def wheel_bytes(package: dict[str, bytes], library: bytes, metadata: bytes, licenses: dict[str, bytes],
                target: str, build: dict) -> bytes:
    """The wheel for ``target``: ``package`` (paths under ``cryptography/``) plus the library; the same
    inputs give the same bytes."""

    dist_info = f"{DISTRIBUTION}-{VERSION}.dist-info"
    files = dict(package)
    files[LIBRARY_IN_WHEEL] = library
    files[f"{dist_info}/METADATA"] = metadata
    files[f"{dist_info}/WHEEL"] = (
        "Wheel-Version: 1.0\n"
        "Generator: scripts/native/build_cryptography_phone.py\n"
        "Root-Is-Purelib: false\n"
        f"Tag: cp314-cp314-{TARGETS[target][2]}\n").encode()
    files[f"{dist_info}/BUILD.json"] = (json.dumps(build, indent=2, sort_keys=True) + "\n").encode("utf-8")
    for name, data in licenses.items():
        files[f"{dist_info}/licenses/{name}"] = data
    record = "".join(f"{name},{_record_hash(data)},{len(data)}\n" for name, data in sorted(files.items()))
    files[f"{dist_info}/RECORD"] = (record + f"{dist_info}/RECORD,,\n").encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith(".so") else 0o644) << 16
            info.create_system = 3
            archive.writestr(info, files[name], compresslevel=9)
    return out.getvalue()


def _safe_extract(archive: Path, into: Path) -> None:
    with tarfile.open(archive) as tar:
        tar.extractall(into, filter="data")


def build_env(source: Path, prefix: Path, toolchain: str = "stable") -> dict[str, str]:
    """The cargo environment: the interpreter's OpenSSL and libpython, paths remapped, symbols stripped."""

    home = Path.home()
    env = dict(os.environ)
    for name in ("RUSTFLAGS", "OPENSSL_STATIC", "OPENSSL_DIR", "PYO3_CROSS", "PYO3_CONFIG_FILE"):
        env.pop(name, None)
    remaps = {"/cargo": Path(env.get("CARGO_HOME", home / ".cargo")),
              "/rustup": Path(env.get("RUSTUP_HOME", home / ".rustup")),
              "/cryptography": source, "/python": prefix}
    env.update({
        "RUSTUP_TOOLCHAIN": toolchain,
        "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_ENCODED_RUSTFLAGS": "\x1f".join(f"--remap-path-prefix={path}={name}"
                                               for name, path in remaps.items()),
        "CARGO_PROFILE_RELEASE_STRIP": "symbols",
        "OPENSSL_LIB_DIR": str(prefix / "lib"),
        "OPENSSL_INCLUDE_DIR": str(prefix / "include"),
        # The interpreter's own names; its libcrypto.so / libssl.so copies carry these SONAMEs too.
        "OPENSSL_LIBS": "ssl_python:crypto_python",
        "OPENSSL_NO_VENDOR": "1",
        "PYO3_PYTHON": sys.executable,
        "PYO3_CROSS_LIB_DIR": str(prefix / "lib"),
        "PYO3_CROSS_PYTHON_VERSION": PYTHON_VERSION,
        "SOURCE_DATE_EPOCH": "315532800",
    })
    return env


def check_toolchain(env: dict[str, str], cwd: Path) -> str:
    found = subprocess.run(["rustc", "-V"], cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if found.returncode != 0 or not found.stdout.startswith(f"rustc {RUST_TOOLCHAIN} "):
        raise BuildRefused(f"this build needs rustc {RUST_TOOLCHAIN}; the toolchain answers "
                           f"{(found.stdout or found.stderr).strip()!r}")
    return found.stdout.strip()


def ndk_version() -> str:
    ndk = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT")
    if not ndk and os.environ.get("ANDROID_HOME"):
        versions = sorted((Path(os.environ["ANDROID_HOME"]) / "ndk").glob("*"))
        ndk = str(versions[-1]) if versions else ""
    props = Path(ndk) / "source.properties" if ndk else None
    if props and props.is_file():
        for line in props.read_text(encoding="utf-8").splitlines():
            if line.startswith("Pkg.Revision"):
                return line.split("=", 1)[1].strip()
    return "unknown"


def needed_libraries(library: bytes) -> list[str]:
    """The ``DT_NEEDED`` names of a 64-bit little-endian ELF shared library."""

    import struct

    if library[:4] != b"\x7fELF" or library[4] != 2 or library[5] != 1:
        raise BuildRefused("not a 64-bit little-endian ELF library")
    (shoff,) = struct.unpack_from("<Q", library, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", library, 0x3A)
    sections = [struct.unpack_from("<IIQQQQIIQQ", library, shoff + i * shentsize) for i in range(shnum)]
    for _name, kind, _flags, _addr, offset, size, link, _info, _align, entsize in sections:
        if kind != 6:  # SHT_DYNAMIC
            continue
        strtab = sections[link]
        names = []
        for at in range(offset, offset + size, entsize or 16):
            tag, value = struct.unpack_from("<qQ", library, at)
            if tag == 0:
                break
            if tag == 1:  # DT_NEEDED
                start = strtab[4] + value
                names.append(library[start:library.index(b"\0", start)].decode("utf-8"))
        return names
    return []


def library_problems(library: bytes, label: str, machine_paths: list[str]) -> list[str]:
    """A machine path left in the library, no link to the interpreter's OpenSSL, or a ``LOAD`` segment
    below 16 KB."""

    problems = [f"machine_path: {label} still holds {path}" for path in machine_paths
                if path and path.encode("utf-8") in library]
    # MUTATION: return [] before this check and a build that fell back to a static OpenSSL is accepted.
    if OPENSSL_SONAME not in needed_libraries(library):
        problems.append(f"openssl_not_shared: {label} does not NEED {OPENSSL_SONAME}")
    misaligned = elf_alignment.problem(label, library)
    return problems + ([misaligned] if misaligned else [])


def pin_problem(target: str, wheel: bytes, doc: dict | None = None) -> str | None:
    pin = phone_wheels.pins(target, doc).get(DISTRIBUTION)
    built = hashlib.sha256(wheel).hexdigest()
    if pin is not None and "path" in pin and pin["sha256"] != built:
        return (f"pin_mismatch: {target} rebuilt as sha256 {built}, the pin is {pin['sha256']}: the build is "
                f"not reproducible here or its inputs moved; never re-pin silently")
    return None


def package_files(source: Path) -> dict[str, bytes]:
    base = source / "src"
    return {path.relative_to(base).as_posix(): path.read_bytes()
            for path in sorted((base / "cryptography").rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}


def build_one(target: str, source: Path, interpreter: Path, sdist_sha: str, scratch: Path,
              toolchain: str) -> tuple[bytes, int]:
    abi, triple, _ = TARGETS[target]
    prefix_root = scratch / f"python-{target}"
    prefix_root.mkdir()
    _safe_extract(interpreter, prefix_root)
    prefix = prefix_root / "prefix"
    env = build_env(source, prefix, toolchain)
    rustc = check_toolchain(env, source)
    run = subprocess.run(["cargo", "ndk", "-t", abi, "--platform", str(API_LEVEL), "build", "--release",
                          "--locked", "-p", "cryptography-rust"], cwd=source, env=env, check=False)
    if run.returncode != 0:
        raise BuildRefused(f"cargo ndk for {abi} exited {run.returncode}")
    library = (source / "target" / triple / "release" / "libcryptography_rust.so").read_bytes()
    problems = library_problems(library, f"{target}/_rust.abi3.so",
                                [str(Path.home()), str(source), str(prefix), str(scratch)])
    if problems:
        raise BuildRefused("; ".join(problems))
    build = {"rustc": rustc, "ndk": ndk_version(), "api_level": API_LEVEL, "target": triple,
             "sdist_sha256": sdist_sha, "interpreter_sha256": INTERPRETERS[target],
             "openssl": "the interpreter's libcrypto_python.so / libssl_python.so (OPENSSL_LIBS)",
             "profile": "release", "strip": "symbols", "locked": True}
    licenses = {name: (source / name).read_bytes() for name in ("LICENSE", "LICENSE.APACHE", "LICENSE.BSD")}
    wheel = wheel_bytes(package_files(source), library, (source / "PKG-INFO").read_bytes(), licenses,
                        target, build)
    return wheel, len(library)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--toolchain", default="stable", help=f"the rustup toolchain that is rustc {RUST_TOOLCHAIN}")
    parser.add_argument("--interpreter", action="append", default=[], metavar="TARGET=ARCHIVE",
                        help="python.org's Android package for a target (repeat per target)")
    args = parser.parse_args(argv)
    try:
        archives = {}
        for item in args.interpreter:
            target, _, path = item.partition("=")
            if target not in TARGETS:
                raise BuildRefused(f"unknown target {target!r}; known: {sorted(TARGETS)}")
            archives[target] = Path(path)
        if not archives:
            raise BuildRefused("name at least one --interpreter TARGET=ARCHIVE")
        check_input(args.sdist, SDIST_SHA256, "sdist")
        for target, path in archives.items():
            check_input(path, INTERPRETERS[target], f"{target} interpreter")
        with tempfile.TemporaryDirectory(prefix="cryptography-phone-") as tmp:
            scratch = Path(tmp)
            _safe_extract(args.sdist, scratch)
            source = scratch / f"{DISTRIBUTION}-{VERSION}"
            for target in sorted(archives):
                wheel, library_size = build_one(target, source, archives[target], SDIST_SHA256, scratch,
                                                 args.toolchain)
                staged = scratch / wheel_name(target)
                staged.write_bytes(wheel)
                misaligned = elf_alignment.wheel_problems(staged)
                if misaligned:
                    raise BuildRefused("; ".join(misaligned))
                refused = pin_problem(target, wheel)
                if refused:
                    raise BuildRefused(refused)
                DIST.mkdir(parents=True, exist_ok=True)
                out = DIST / wheel_name(target)
                out.write_bytes(wheel)
                pin = phone_wheels.pins(target).get(DISTRIBUTION, {})
                print(f"{target}: {out.relative_to(ROOT).as_posix()} {len(wheel)} B (library {library_size} B) "
                      f"sha256 {hashlib.sha256(wheel).hexdigest()} "
                      f"{'matches its pin' if 'path' in pin else 'NOT PINNED BY PATH'}", flush=True)
    except BuildRefused as refused:
        print(f"refused: {refused}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
