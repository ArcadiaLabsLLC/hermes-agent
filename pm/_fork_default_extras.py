"""Fork-owned: the Developer Edition's default extra set — upstream's ``all`` plus the provider SDKs.

Owner ruling 2026-10-15 (wave w1015c-dev): a first setup of the repo installs every provider SDK
the Launcher's Connections offers, so a fresh source install can run a Claude agent without a hand
install. Upstream's ``all`` extra is never edited; this module is the ONE list, read by:

* setup and ``hermes pm install`` — both reach ``pm.install.sync_venv``, whose selection
  ``pm.install._target_selection`` is rebound through :func:`widen_target_selection` (tail of
  ``pm/install.py``, ledger row ``pm/install.py``);
* the test environment default — ``pm.testenv.DEFAULT_TEST_EXTRAS`` (tail of ``pm/testenv.py``).

An existing environment whose selection lacks one gets it at its next sync (``hermes update``,
``hermes pm install``): the widened selection changes the stamp, and pm's own sync installs the
extra and records it in the feature ledger, so later generations keep it. The one-extra in-place
install (``pm._fork_extend_environment``) stays the Connections row's answer between syncs.

Not widened: a bundled payload (``enabled-features.json`` ships its SDKs — ``shipped`` is set), a
selection without ``all`` (someone chose a minimal install), a repair (restores, never adds), and a
process under ``HERMES_DISABLE_LAZY_INSTALLS`` (the Docker image and the hermetic test harness: a
non-explicit sync there must stay a no-op, not a refusal). The config-level
``security.allow_lazy_installs`` is deliberately NOT read here: explicit source setup must not load
config (``pm.install._feature_policy``).
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = ["DEFAULT_EXTRAS", "PROVIDER_SDK_EXTRAS", "provider_extras_for", "widen_target_selection"]

#: The pm extras behind the providers the Launcher's Connections offers. One entry per value of
#: ``hermes_cli.runtime_environment._PM_EXTRA_FOR_DISTRIBUTION`` (pinned by a test), anthropic first.
PROVIDER_SDK_EXTRAS: tuple[str, ...] = ("anthropic", "bedrock", "vertex", "azure-identity")

#: The Developer Edition's first-setup selection.
DEFAULT_EXTRAS: tuple[str, ...] = ("all", *PROVIDER_SDK_EXTRAS)


def _lazy_installs_disabled_by_environment() -> bool:
    import os

    return os.environ.get("HERMES_DISABLE_LAZY_INSTALLS", "").strip().lower() in ("1", "true", "yes")


def provider_extras_for(package: Any, selection: list[str], *, shipped: list[str] | None,
                        repair: bool) -> list[str]:
    """The provider extras a sync of ``selection`` adds — empty when the selection is not widened.

    Only extras the tree still declares (:func:`_declared_only`): an undeclared one would fail the
    ``uv sync`` with "Extra is not defined"."""
    if repair or shipped is not None or "all" not in selection:
        return []
    if _lazy_installs_disabled_by_environment():
        return []
    from pm.extras import extra_supported

    wanted = [extra for extra in PROVIDER_SDK_EXTRAS
              if extra not in selection and extra_supported(extra, importable=lambda _anchor: False)]
    return _declared_only(package, wanted) if wanted else []


def _declared_only(package: Any, wanted: list[str]) -> list[str]:
    """``wanted`` less every extra the tree's ``pyproject.toml`` no longer declares.

    Built on pm's PUBLIC ``pm.features.declared_extras``, never ``pm.install._still_declared``
    (W0-G6: no fork module imports a ``_private`` upstream name). Names compare as uv matches
    them, PEP 685-normalized (``packaging.utils.canonicalize_name``); a tree without a
    ``pyproject.toml`` (a bundled payload) keeps ``wanted`` whole, as pm's own prune does."""
    from packaging.utils import canonicalize_name

    from pm.features import declared_extras

    root = package.project_root()
    if not (root / "pyproject.toml").is_file():
        return list(wanted)
    declared = {canonicalize_name(extra) for extra in declared_extras(root)}
    return [extra for extra in wanted if canonicalize_name(extra) in declared]


def widen_target_selection(select: Callable[..., tuple[list[str], str, dict]]) -> Callable[..., tuple[list[str], str, dict]]:
    """``pm.install._target_selection`` that also carries :data:`PROVIDER_SDK_EXTRAS`."""
    if getattr(select, "__fork_default_extras__", False):
        return select

    def _target_selection(package: Any, fact: dict, *, extras, inputs: dict, repair: bool, shipped, frozen):
        enabled, stamp, chosen = select(package, fact, extras=extras, inputs=inputs, repair=repair,
                                        shipped=shipped, frozen=frozen)
        added = provider_extras_for(package, enabled, shipped=shipped, repair=repair)
        if not added:
            return enabled, stamp, chosen
        widened = sorted(set(enabled) | set(added))
        return widened, package.expected_stamp(widened, **chosen), chosen

    _target_selection.__fork_default_extras__ = True  # type: ignore[attr-defined]
    _target_selection.__wrapped__ = select  # type: ignore[attr-defined]
    return _target_selection
