"""Provider packs: the provider SDKs the bundled Eternia Harness downloads instead of shipping.

OWNER RULING 2026-10-15: each provider SDK the wheel does not carry (``bedrock``,
``vertex``, ``azure-identity``, ``mistral``) is built as its own engine pack per
release — ``packaging.packs.provider-<extra>`` in
``agent_runtime/bundle_profiles/bundled-desktop.yaml`` — and the Launcher downloads
it only when the user signs in to that provider. The runtime never downloads
(``security.allow_lazy_installs`` stays false); it answers two questions:

* :func:`pack_for_extra` — which pack carries a missing provider extra, read from
  the bundle's own record (``bundle-manifest.json`` ``packs``, written by
  ``scripts/bundle_profile_package.py``). A source checkout (the Developer
  Edition) has no record and no packs: it installs the extra instead.
* :func:`activate_pack` — put an unpacked pack on this process's import path
  without a restart (``runtime.provider.pack.activate``). A runtime started
  after the unpack finds the pack through ``HERMES_ENGINE_PACKS`` and the core's
  ``hermes-engine-packs.pth``, the speech pack's door; this is the same
  ``site.addsitedir`` that ``.pth`` line runs, for a runtime already up.

Phones are SDK-free and never reach either (``provider_dependencies._sdk_free``).
"""

from __future__ import annotations

import importlib
import json
import os
import site
import sys
from pathlib import Path
from typing import Any

__layer__ = "stores"

__all__ = [
    "BUNDLE_RECORD",
    "ENGINE_PACKS_ENV",
    "PACK_RECORD",
    "PROVIDER_PACK_PREFIX",
    "activate_pack",
    "bundle_packs",
    "pack_for_extra",
]

#: The packager's record beside ``app/`` (``scripts/bundle_profile_package.BUNDLE_MANIFEST``).
BUNDLE_RECORD = "bundle-manifest.json"
#: The packager's record at an engine pack's root (``…PACK_MANIFEST``).
PACK_RECORD = "engine-pack.json"
#: The variable the core's ``hermes-engine-packs.pth`` reads (``…ENGINE_PACKS_ENV``).
ENGINE_PACKS_ENV = "HERMES_ENGINE_PACKS"
#: Every provider pack's name starts with this; the speech pack does not.
PROVIDER_PACK_PREFIX = "provider-"

#: ``app/agent_runtime/provider_packs.py`` -> the bundle root holding ``bundle-manifest.json``.
_APP_DIR = Path(__file__).resolve().parents[1]


def _bundle_record(app_dir: Path | None = None) -> dict | None:
    """The bundle's record, or None outside a bundle (a checkout's root is not named ``app``)."""
    app = app_dir or _APP_DIR
    if app.name != "app":
        return None
    try:
        record = json.loads((app.parent / BUNDLE_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def bundle_packs(app_dir: Path | None = None) -> tuple[str | None, dict[str, tuple[str, ...]]]:
    """``(commit, {pack: extras})`` this bundle was built with; ``(None, {})`` outside one."""
    record = _bundle_record(app_dir)
    if record is None:
        return None, {}
    packs = record.get("packs")
    if not isinstance(packs, dict):
        return None, {}
    commit = record.get("commit") if isinstance(record.get("commit"), str) else None
    return commit, {str(name): tuple(str(e) for e in extras)
                    for name, extras in packs.items() if isinstance(extras, list)}


def pack_for_extra(extra: str | None, app_dir: Path | None = None) -> dict | None:
    """``{name, commit}`` of the provider pack that carries ``extra`` in this bundle, else None."""
    if not extra:
        return None
    commit, packs = bundle_packs(app_dir)
    for name in sorted(packs):
        if name.startswith(PROVIDER_PACK_PREFIX) and extra in packs[name]:
            return {"name": name, "commit": commit}
    return None


def _refused(reason: str, **data: Any) -> Exception:
    from agent_runtime.provider_account import ProviderRefused

    return ProviderRefused(reason, **data)


def activate_pack(site_packages: str, app_dir: Path | None = None) -> dict:
    """Put the unpacked pack whose ``site-packages`` is ``site_packages`` on the import path.

    The pack must be one this bundle offers, built from this bundle's commit (its
    ``engine-pack.json`` one level up says so) — a pack from another release would
    load an SDK the core was never resolved against. Idempotent.
    ``{pack, site_packages, activated}``: ``activated`` is False when it was already on the path.
    """
    commit, packs = bundle_packs(app_dir)
    if not packs:
        raise _refused("not_a_bundle")
    directory = Path(site_packages)
    if not directory.is_absolute() or not directory.is_dir():
        raise _refused("pack_not_found")
    try:
        record = json.loads((directory.parent / PACK_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _refused("pack_not_found") from None
    name = record.get("pack") if isinstance(record, dict) else None
    if name not in packs:
        raise _refused("pack_unknown", pack=name if isinstance(name, str) else None)
    if commit is None or record.get("commit") != commit:
        raise _refused("pack_mismatch", pack=name)
    resolved = str(directory.resolve())
    already = any(_same_path(resolved, entry) for entry in sys.path)
    if not already:
        site.addsitedir(resolved)
        importlib.invalidate_caches()
        # A child this runtime starts inherits the pack, as one started after a restart would.
        listed = [p for p in os.environ.get(ENGINE_PACKS_ENV, "").split(os.pathsep) if p]
        if not any(_same_path(resolved, p) for p in listed):
            os.environ[ENGINE_PACKS_ENV] = os.pathsep.join([*listed, resolved])
    return {"pack": name, "site_packages": resolved, "activated": not already}


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (TypeError, ValueError):
        return False
