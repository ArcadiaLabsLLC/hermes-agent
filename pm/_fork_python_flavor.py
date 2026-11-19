"""Fork-owned: which python-build-standalone build PM pins per target (RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED).

Ledger row ``pm/packages.py``: the module's tail hands the ``Python`` package to
:func:`flavor_python_downloads`, so its ``fetch_url`` — the one place PM builds the interpreter's
download URL, read by ``pm update``'s re-pin (``pm.cli._pin_artifacts``) and ``pm lock --bump`` alike
— names the build :data:`PBS_FLAVOR` sets for that target. ``pm/lock.json``'s ``packages.python`` is
written through it, and ``agent_runtime/bundle_profiles/interpreters.lock.json`` copies that pin
(``tests/agent_runtime/test_bundle_interpreters_lock.py``), so this table is the one owner of the
flavor.

``pm update``'s release match (``pm.update.pbs_versions``) is left as upstream wrote it: it reads the
interpreter IDENTITY (``3.14.9+20261021``) off the ``install_only`` asset, and python-build-standalone
publishes ``install_only_stripped`` beside it in the same release for every Linux triple, so the
identity is the same for both flavors. A release that ever lacked the stripped asset fails the
re-pin loudly (the URL 404s when it is hashed), never silently pins the debug build.

Why stripped on Linux: the debug build's ``bin/python3.14`` is 79 MB (32.5 MB stripped), and the
bundled interpreter ships in Eternia's Linux download (Eternia
``docs/stages/installer-distribution/LINUX_APPIMAGE_SIZE_2026-11-19.md``). Stripping by hand broke
the binary there, so the build must be upstream's. Upstream PR candidate: a per-target flavor on
``Python``.
"""

from __future__ import annotations

__all__ = ["DEFAULT_FLAVOR", "PBS_FLAVOR", "flavor_python_downloads", "pbs_flavor"]

#: python-build-standalone's default archive flavor (the one upstream's ``fetch_url`` names).
DEFAULT_FLAVOR = "install_only"

#: Targets whose pin is a different flavor. The desktop bundle's Linux targets take upstream's
#: stripped build (no debug info); macOS and Windows keep ``install_only`` (Windows' debug data is
#: the ``.pdb`` files the bundle prune already drops; macOS is unmeasured).
PBS_FLAVOR: dict[str, str] = {
    "linux-x64": "install_only_stripped",
    "linux-arm64": "install_only_stripped",
}

_SUFFIX = f"-{DEFAULT_FLAVOR}.tar.gz"


def pbs_flavor(target: str) -> str:
    """The python-build-standalone archive flavor PM pins for ``target``."""
    return PBS_FLAVOR.get(target, DEFAULT_FLAVOR)


def flavor_python_downloads(python_cls: type) -> type:
    """Wrap ``python_cls.fetch_url`` so a python-build-standalone URL names :func:`pbs_flavor`'s build."""
    upstream_fetch_url = python_cls.fetch_url

    def fetch_url(self, version: str, target: str) -> str:
        url = upstream_fetch_url(self, version, target)
        flavor = pbs_flavor(target)
        if flavor == DEFAULT_FLAVOR or not url.endswith(_SUFFIX):
            return url
        return f"{url[: -len(_SUFFIX)]}-{flavor}.tar.gz"

    fetch_url.__doc__ = upstream_fetch_url.__doc__
    python_cls.fetch_url = fetch_url
    return python_cls
