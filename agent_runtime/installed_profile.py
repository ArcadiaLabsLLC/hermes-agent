"""What the INSTALLED bundle profile switches off — the one owner of that list, read below every gate.

A bundled install is a phone (CPython's mobile platforms run only the embedded phone profile) or a desktop
whose build stamp says ``bundled``; a developer install switches nothing off. Its profile's
``packaging.switched_off_modules`` is a profile fact, never a presence probe: a switched-off module kept
code imports unguarded still ships (pinned), so ``module_presence.shipped`` answers True for it
(``agent_runtime.work`` on the phone). ``module_presence.runs_here`` asks both.

``models``, so a host or model gate (``host_tools``, ``module_presence``) can ask it: it reads the profile's
YAML itself rather than through ``bundle_profiles.manifest`` (``policy``), which parses and validates the
whole manifest for the packager. ``bundled_toolsets`` delegates to it (RT-FU-A-PHONE-RUNS-A-FEATURE-ONLY-WHEN-ITS-PROFILE-SWITCHES-IT-ON).
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path

__layer__ = "models"  # a pure read of a shipped file: host and model gates ask it
__all__ = ["DESKTOP_PROFILE", "PHONE_PLATFORMS", "PHONE_PROFILE", "edition_bundled", "install_is_bundled",
           "installed_profile_name", "installed_switched_off", "switched_off_modules"]

#: ``sys.platform`` of CPython's mobile builds: the embedded entry runs the phone profile there.
PHONE_PLATFORMS = frozenset({"android", "ios"})
PHONE_PROFILE = "bundled-phone"
DESKTOP_PROFILE = "bundled-desktop"
#: Where ``<profile>.yaml`` ships (``bundle_profiles.manifest.PROFILES_DIR``).
PROFILES_DIR = Path(__file__).resolve().parent / "bundle_profiles"


def edition_bundled() -> bool:
    """The build stamp's answer (``namespace.install_stamp``), never a config value."""
    from .namespace import install_stamp

    return install_stamp().get("edition") == "bundled"


def install_is_bundled() -> bool:
    """A phone, or a desktop whose build stamp says ``bundled``: an install a bundle profile governs."""
    return sys.platform in PHONE_PLATFORMS or edition_bundled()


def installed_profile_name() -> str:
    return PHONE_PROFILE if sys.platform in PHONE_PLATFORMS else DESKTOP_PROFILE


@functools.lru_cache(maxsize=4)
def switched_off_modules(profile: str) -> tuple[str, ...]:
    """``packaging.switched_off_modules`` of ``<profile>.yaml``; ``()`` when it names none."""
    from . import yaml_io

    document = yaml_io.load((PROFILES_DIR / f"{profile}.yaml").read_text(encoding="utf-8")) or {}
    modules = (document.get("packaging") or {}).get("switched_off_modules") or ()
    return tuple(str(module) for module in modules)


def installed_switched_off(module: str) -> bool:
    """True when the INSTALLED bundle profile switches ``module`` (or a package holding it) off."""
    if not install_is_bundled():
        return False
    return any(module == off or module.startswith(off + ".")
               for off in switched_off_modules(installed_profile_name()))
