"""Build the ``eternia-project-files-match`` library wheel: ripgrep's matcher for an Android phone.

Fork-owned (row ``RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID``, plan
``docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md`` §6). The phone packager
builds nothing from source: this script is run by hand, its wheels are committed under
``crates/project_files_match/dist/`` and pinned by repo-relative path and sha256 in
``agent_runtime/bundle_profiles/phone_wheels.lock.json`` (owner RULED 2026-11-21: "yea commit them to the
hermes fork which is public").

    python scripts/native/build_project_files_match.py --toolchain stable [--target android_arm64 ...]

* **The build.** ``cargo ndk -t <abi> --platform 24 build --release --locked`` in the crate, under the
  toolchain the crate's ``rust-toolchain.toml`` names: ``--toolchain`` is the rustup name to run (this box
  installs 1.100.0 as ``stable``), and the build is refused unless its ``rustc -V`` is that channel.
  ``RUSTUP_AUTO_INSTALL=0``: a missing toolchain is a refusal, never a download.
  ``--remap-path-prefix`` maps the crate, ``CARGO_HOME`` and ``RUSTUP_HOME`` to fixed names, and the
  library is refused if the home folder or the crate's path is still in it.
* **The wheel.** ``eternia_project_files_match/`` holds the library and a locator, ``LIBRARY``, the
  library's path (``agent_runtime/project_files/native_match.py`` imports it inside an ImportError guard).
  It is not a CPython extension, so it is tagged ``py3-none-android_24_<abi>`` and fits every CPython.
  The zip is written deterministically (sorted entries, fixed times and modes). ``BUILD.json`` in the
  dist-info records the toolchain, the NDK, the API level and ``Cargo.lock``'s sha256.
* **The pin is never moved here.** A target with a pin: the rebuilt wheel must have the pinned sha256, or
  the run is refused and the committed wheel is left as it is. A target with no pin: the wheel is written
  to ``dist/`` and its sha256 printed; pinning it is a reviewed edit of the lock file.
* **16 KB pages.** The library is refused when a ``LOAD`` segment is aligned below ``0x4000``
  (``scripts/bundles/elf_alignment.py``).
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
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bundles import elf_alignment  # noqa: E402
from scripts.bundles import phone_wheels  # noqa: E402

CRATE = ROOT / "crates" / "project_files_match"
DIST = CRATE / "dist"
DISTRIBUTION = "eternia-project-files-match"
PACKAGE = "eternia_project_files_match"
LIBRARY_FILE = "libproject_files_match.so"
API_LEVEL = 24
#: phone target -> (cargo-ndk ABI, Rust target triple, wheel platform tag)
TARGETS = {
    "android_arm64": ("arm64-v8a", "aarch64-linux-android", f"android_{API_LEVEL}_arm64_v8a"),
    "android_x86_64": ("x86_64", "x86_64-linux-android", f"android_{API_LEVEL}_x86_64"),
}
#: The zip time of every entry (the zip format's earliest), so a rebuild writes the same bytes.
ZIP_TIME = (1980, 1, 1, 0, 0, 0)

LOCATOR = '''"""Where ripgrep's matcher library is: ``LIBRARY`` (row RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID)."""

from pathlib import Path

LIBRARY = str(Path(__file__).with_name("{library}"))
'''


class BuildRefused(RuntimeError):
    """The build or its wheel failed a rule above; the message says which."""


def crate_version() -> str:
    return tomllib.loads((CRATE / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]


def toolchain_channel() -> str:
    return tomllib.loads((CRATE / "rust-toolchain.toml").read_text(encoding="utf-8"))["toolchain"]["channel"]


def wheel_name(version: str, target: str) -> str:
    return f"{PACKAGE}-{version}-py3-none-{TARGETS[target][2]}.whl"


def _record_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def wheel_bytes(library: bytes, version: str, target: str, build: dict) -> bytes:
    """The wheel holding ``library`` for ``target``: the same inputs give the same bytes."""

    dist_info = f"{PACKAGE}-{version}.dist-info"
    files = {
        f"{PACKAGE}/__init__.py": LOCATOR.format(library=LIBRARY_FILE).encode("utf-8"),
        f"{PACKAGE}/{LIBRARY_FILE}": library,
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {DISTRIBUTION}\n"
            f"Version: {version}\n"
            "Summary: ripgrep's matcher (grep-regex + grep-searcher) as a C-ABI library for Hermes on a phone\n"
            "License: MIT\n").encode("utf-8"),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: scripts/native/build_project_files_match.py\n"
            "Root-Is-Purelib: false\n"
            f"Tag: py3-none-{TARGETS[target][2]}\n").encode("utf-8"),
        f"{dist_info}/BUILD.json": (json.dumps(build, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    record = "".join(f"{name},{_record_hash(data)},{len(data)}\n" for name, data in sorted(files.items()))
    files[f"{dist_info}/RECORD"] = (record + f"{dist_info}/RECORD,,\n").encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith(".so") else 0o644) << 16
            info.create_system = 3  # unix, so the mode above is read
            archive.writestr(info, files[name], compresslevel=9)
    return out.getvalue()


def _homes() -> dict[str, Path]:
    home = Path.home()
    return {"/cargo": Path(os.environ.get("CARGO_HOME", home / ".cargo")),
            "/rustup": Path(os.environ.get("RUSTUP_HOME", home / ".rustup")),
            "/crate": CRATE}


def build_env(toolchain: str) -> dict[str, str]:
    env = dict(os.environ)
    env["RUSTUP_TOOLCHAIN"] = toolchain
    env["RUSTUP_AUTO_INSTALL"] = "0"
    env["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(f"--remap-path-prefix={path}={name}"
                                                  for name, path in _homes().items())
    env.pop("RUSTFLAGS", None)
    return env


def check_toolchain(env: dict[str, str]) -> str:
    """``rustc -V`` under ``env``; refused unless it is the channel ``rust-toolchain.toml`` names."""

    found = subprocess.run(["rustc", "-V"], cwd=CRATE, env=env, capture_output=True, text=True)
    channel = toolchain_channel()
    if found.returncode != 0 or not found.stdout.startswith(f"rustc {channel} "):
        raise BuildRefused(f"rust-toolchain.toml names {channel}; this toolchain answers "
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


def build_library(target: str, env: dict[str, str]) -> bytes:
    abi, triple, _ = TARGETS[target]
    run = subprocess.run(["cargo", "ndk", "-t", abi, "--platform", str(API_LEVEL), "build", "--release",
                          "--locked"], cwd=CRATE, env=env)
    if run.returncode != 0:
        raise BuildRefused(f"cargo ndk for {abi} exited {run.returncode}")
    return (CRATE / "target" / triple / "release" / LIBRARY_FILE).read_bytes()


def library_problems(library: bytes, label: str) -> list[str]:
    """A machine path left in the library, or a ``LOAD`` segment below 16 KB."""

    problems = [f"machine_path: {label} still holds {path}" for path in {str(Path.home()), str(CRATE)}
                if path.encode("utf-8") in library]
    misaligned = elf_alignment.problem(label, library)
    return problems + ([misaligned] if misaligned else [])


def pin_problem(target: str, wheel: bytes, doc: dict | None = None) -> str | None:
    """The refusal when ``target`` is pinned and ``wheel`` is not the pinned wheel; None otherwise."""

    pin = phone_wheels.pins(target, doc).get(DISTRIBUTION)
    built = hashlib.sha256(wheel).hexdigest()
    # MUTATION: return None here and a rebuild that differs from its pin overwrites the committed wheel
    # (test_build_project_files_match: test_a_rebuild_off_the_pin_is_refused_and_the_wheel_is_kept).
    if pin is not None and pin["sha256"] != built:
        return (f"pin_mismatch: {target} rebuilt as sha256 {built}, the pin is {pin['sha256']}: the build is "
                f"not reproducible here or its inputs moved; never re-pin silently")
    return None


def write_wheel(target: str, wheel: bytes, version: str, dist: Path = DIST, doc: dict | None = None) -> Path:
    """Write ``wheel`` to ``dist`` unless it is off its pin (``BuildRefused``, nothing written)."""

    refused = pin_problem(target, wheel, doc)
    if refused:
        raise BuildRefused(refused)
    dist.mkdir(parents=True, exist_ok=True)
    out = dist / wheel_name(version, target)
    out.write_bytes(wheel)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--toolchain", default=None,
                        help="the rustup toolchain to run (default: the channel rust-toolchain.toml names)")
    parser.add_argument("--target", action="append", choices=sorted(TARGETS), dest="targets")
    args = parser.parse_args(argv)
    env = build_env(args.toolchain or toolchain_channel())
    version = crate_version()
    try:
        rustc = check_toolchain(env)
        lock_sha = hashlib.sha256((CRATE / "Cargo.lock").read_bytes()).hexdigest()
        for target in args.targets or sorted(TARGETS):
            library = build_library(target, env)
            problems = library_problems(library, f"{target}/{LIBRARY_FILE}")
            if problems:
                raise BuildRefused("; ".join(problems))
            build = {"rustc": rustc, "ndk": ndk_version(), "api_level": API_LEVEL, "target": TARGETS[target][1],
                     "cargo_lock_sha256": lock_sha, "profile": "release", "locked": True}
            with tempfile.TemporaryDirectory() as scratch:
                staged = Path(scratch) / wheel_name(version, target)
                staged.write_bytes(wheel_bytes(library, version, target, build))
                misaligned = elf_alignment.wheel_problems(staged)
                if misaligned:
                    raise BuildRefused("; ".join(misaligned))
                wheel = staged.read_bytes()
            out = write_wheel(target, wheel, version)
            pinned = DISTRIBUTION in phone_wheels.pins(target)
            print(f"{target}: {out.relative_to(ROOT).as_posix()} {len(wheel)} B (library {len(library)} B) "
                  f"sha256 {hashlib.sha256(wheel).hexdigest()} {'matches its pin' if pinned else 'NOT PINNED'}",
                  flush=True)
    except BuildRefused as refused:
        print(f"refused: {refused}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
