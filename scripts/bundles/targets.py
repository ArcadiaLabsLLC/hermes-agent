"""The packager's targets: ``pm/lock.json`` target name -> uv platform and PEP 508 marker environment.

Split out of ``scripts/bundle_profile_package.py`` (W0-G1 size ceiling, row RT-PACKAGER-CEILING-800).
:func:`marker_env` is the one target authority: the pool's marker evaluation and the planning child
(``scripts/bundles/plan.py``) both read it.
"""

from __future__ import annotations


#: pm/lock.json target name -> (uv --python-platform, PEP 508 marker environment)
TARGETS: dict[str, tuple[str, dict[str, str]]] = {
    "win32-x64": ("x86_64-pc-windows-msvc",
                  {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt",
                   "platform_machine": "AMD64"}),
    "win32-arm64": ("aarch64-pc-windows-msvc",
                    {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt",
                     "platform_machine": "ARM64"}),
    "darwin-arm64": ("aarch64-apple-darwin",
                     {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix",
                      "platform_machine": "arm64"}),
    "darwin-x64": ("x86_64-apple-darwin",
                   {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix",
                    "platform_machine": "x86_64"}),
    "linux-x64": ("x86_64-unknown-linux-gnu",
                  {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix",
                   "platform_machine": "x86_64"}),
    "linux-arm64": ("aarch64-unknown-linux-gnu",
                    {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix",
                     "platform_machine": "aarch64"}),
    # The phones (manifest.PACKAGING_TARGETS): no interpreter pin — the host app embeds CPython.
    "android_arm64": ("aarch64-linux-android",
                      {"sys_platform": "android", "platform_system": "Android", "os_name": "posix",
                       "platform_machine": "aarch64"}),
    "ios_arm64": ("arm64-apple-ios",
                  {"sys_platform": "ios", "platform_system": "iOS", "os_name": "posix",
                   "platform_machine": "arm64"}),
}


def marker_env(target: str, python_version: str) -> dict[str, str]:
    _, env = TARGETS[target]
    full = python_version if python_version.count(".") >= 2 else f"{python_version}.0"
    return {**env, "python_version": ".".join(full.split(".")[:2]), "python_full_version": full,
            "implementation_name": "cpython", "platform_python_implementation": "CPython",
            "platform_release": "", "platform_version": "", "extra": ""}
