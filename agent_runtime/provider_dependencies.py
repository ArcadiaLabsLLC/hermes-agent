"""Missing provider SDKs: the report a Connections row reads, and the one-extra install.

OWNER RULING 2026-10-15: a provider whose SDK is not installed shows a WARNING on its
own Connections row, and the fix offered there installs only that provider's extra —
never a whole-runtime repair. The phone edition is SDK-free (``agent.provider_sdks:
false`` builds raw-HTTP clients), so it reports nothing missing and refuses an install.

* report  -> :func:`provider_dependency_report`, the ``dependencies`` block of
             ``runtime.provider.list``. One authority on "what does a provider need":
             ``hermes_cli.runtime_environment`` (the table the pre-turn check uses).
* install -> :func:`install_provider_dependency`, ``runtime.provider.dependency.install``.
             The extra goes INTO the environment this runtime runs from (``uv pip
             install`` of the extra's pinned requirements, ``pm._fork_extend_environment``);
             a new environment
             generation (``pm`` sync) is built only when the in-place install
             conflicts. A Windows sharing violation (``os error 32``: a file the serve
             or a scanner holds) is waited out and retried before it is reported.

Known gap, on purpose: an in-place install does not enter ``pm``'s feature ledger, so
a later generation built for another reason starts without it; the report then names
the provider again and the same one-press install answers it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Callable

__layer__ = "stores"

__all__ = [
    "INSTALL_TIMEOUT_SECONDS",
    "install_provider_dependency",
    "provider_dependency_report",
]

#: The bound on one ``uv pip install`` attempt.
INSTALL_TIMEOUT_SECONDS = 300

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _sdk_free() -> bool:
    from agent.transports.httpx_client import provider_sdks_enabled

    return not provider_sdks_enabled()


def _extra_for(missing: list[str]) -> str | None:
    """The one ``pm`` extra that installs every missing distribution, or None."""
    from hermes_cli.runtime_environment import _PM_EXTRA_FOR_DISTRIBUTION
    from hermes_cli.venv_integrity import canonical_distribution

    extras = {_PM_EXTRA_FOR_DISTRIBUTION.get(canonical_distribution(item)) for item in missing}
    return extras.pop() if len(extras) == 1 and None not in extras else None


def _supported(extra: str) -> bool:
    try:
        from pm.extras import extra_supported

        return bool(extra_supported(extra))
    except Exception:  # a stripped install without pm: offer the install, let it refuse
        return True


def provider_dependency_report() -> dict:
    """``{sdk_free, providers: [{provider, missing, extra, installable, pack_available, pack}]}``.

    Missing ones only. In a bundle (the Eternia Harness) nothing is installable — the
    runtime never installs (``security.allow_lazy_installs: false``) — and a provider
    whose extra a provider pack carries reports ``pack_available: true`` with
    ``pack: {name, commit}``: the Launcher downloads that pack
    (:mod:`agent_runtime.provider_packs`). Elsewhere ``pack`` is null.
    """
    if _sdk_free():
        return {"sdk_free": True, "providers": []}
    from agent_runtime.provider_packs import bundle_packs, pack_for_extra
    from hermes_cli.runtime_environment import (
        _PROVIDER_PACKAGE_REQUIREMENTS,
        missing_runtime_packages_for,
        runtime_environment_status_scope,
    )

    bundled = bool(bundle_packs()[1])
    rows = []
    with runtime_environment_status_scope():
        for provider in sorted(_PROVIDER_PACKAGE_REQUIREMENTS):
            missing = missing_runtime_packages_for(provider=provider)
            if not missing:
                continue
            extra = _extra_for(missing)
            pack = pack_for_extra(extra) if bundled else None
            rows.append({
                "provider": provider,
                "missing": missing,
                "extra": extra,
                "installable": not bundled and extra is not None and _supported(extra),
                "pack_available": pack is not None,
                "pack": pack,
            })
    return {"sdk_free": False, "providers": rows}


def _extra_requirements(extra: str) -> list[str]:
    import tomllib

    with (_REPO_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    requirements = project.get("optional-dependencies", {}).get(extra)
    if not requirements:
        raise _refused("dependency_not_installable", extra=extra)
    return list(requirements)


def _refused(reason: str, **data: Any) -> Exception:
    from agent_runtime.provider_account import ProviderRefused

    return ProviderRefused(reason, **data)


def _extend(requirements: list[str]) -> bool:
    from pm._fork_extend_environment import extend_environment

    return extend_environment(requirements, environment=Path(sys.prefix), explicit=True,
                              timeout=INSTALL_TIMEOUT_SECONDS)


def _new_generation(extra: str) -> None:
    from pm.client import sync_venv

    sync_venv([extra], explicit=True)


def install_provider_dependency(
    provider: str,
    *,
    extend: Callable[[list[str]], bool] | None = None,
    new_generation: Callable[[str], None] | None = None,
) -> dict:
    """Install ``provider``'s one missing extra; ``{provider, extra, outcome, environment, restart_required}``.

    ``outcome`` is ``already_installed`` or ``installed``; ``environment`` is ``existing``
    (in place, live for this runtime) or ``new`` (a new generation: restart to load it).
    """
    from hermes_cli.runtime_environment import missing_runtime_packages_for

    if _sdk_free():
        raise _refused("sdk_free_edition", provider=provider)
    missing = missing_runtime_packages_for(provider=provider)
    if not missing:
        return {"provider": provider, "extra": None, "outcome": "already_installed",
                "environment": "existing", "restart_required": False}
    extra = _extra_for(missing)
    from agent_runtime.provider_packs import bundle_packs, pack_for_extra

    if bundle_packs()[1]:  # a bundle never installs: the Launcher downloads the pack
        pack = pack_for_extra(extra)
        raise _refused("pack_required" if pack else "dependency_not_installable",
                       provider=provider, missing=missing, **({"pack": pack["name"]} if pack else {}))
    if extra is None or not _supported(extra):
        raise _refused("dependency_not_installable", provider=provider, missing=missing)
    try:
        in_place = (extend or _extend)(_extra_requirements(extra))
    except Exception as exc:  # pm.package.InstallError, or the toolchain absent
        if "os error 32" in str(exc).lower():
            raise _refused("environment_busy", provider=provider, extra=extra) from exc
        raise _refused("install_failed", provider=provider, extra=extra,
                       error_class=type(exc).__name__) from exc
    if in_place:
        importlib.invalidate_caches()
        return _installed(provider, extra, "existing")
    (new_generation or _new_generation)(extra)
    return _installed(provider, extra, "new")


def _installed(provider: str, extra: str, environment: str) -> dict:
    return {"provider": provider, "extra": extra, "outcome": "installed",
            "environment": environment, "restart_required": environment == "new"}
