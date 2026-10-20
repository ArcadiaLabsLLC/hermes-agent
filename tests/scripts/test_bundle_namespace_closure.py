"""The bundled-desktop closure carries the namespace machinery (row RT-NAMESPACE-IN-BUNDLE-CLOSURE)
and omits its Developer Edition half (row RT-NAMESPACE-SEED-HIRED-INSTANCES).

Players run the bundled edition, never the Developer Edition (owner 2026-10-19, plan §2.7): a
bundle without the resolver ignores ``HERMES_NAMESPACE`` and every launcher profile writes the base
root, and without ``hermes namespace probe`` the launcher's pre-spawn check cannot tell. The proof is
the packager's own plan (``scripts/bundle_profile_package.py::first_party_plan``) over the real
profile — what the bundle ships — not a read of the YAML.
"""

from __future__ import annotations

import pytest

from agent_runtime.bundle_profiles.manifest import load_profile
from scripts.bundle_profile_package import first_party_plan

NAMESPACE_MODULES = {
    "hermes_cli._namespace_bootstrap",  # the resolver main.py runs before any hermes import
    "hermes_cli.namespace_cmd",  # `hermes namespace probe | list | reset | delete` (+ the dev-only refusals)
    "agent_runtime.namespace",  # the store-root isolation gate
    "agent_runtime.namespace_admin",  # the admin verbs
}
#: Developer Edition only (owner 2026-10-19): the code that carries instances and chats between
#: namespaces is not in a player's bundle at all — not merely refused.
DEV_ONLY_MODULES = {
    "agent_runtime.namespace_seed",
    "agent_runtime.namespace_seed.seed",
    "agent_runtime.namespace_seed.instances",
    "agent_runtime.own_session_import",
}


@pytest.fixture(scope="module")
def shipped() -> set[str]:
    """What the packager ships for the bundled desktop: its own plan (kept + forced + parents)."""
    modules, _forced, _index = first_party_plan(load_profile("bundled-desktop"))
    return modules


@pytest.mark.timeout(300)  # the desktop walk (~65 s cold, like the phone walk's ~40 s)
def test_the_bundled_desktop_closure_ships_the_namespace_machinery(shipped: set[str]):
    assert "hermes_cli.main" in shipped  # positive control: the walk reached the serve entry
    assert NAMESPACE_MODULES - shipped == set()


@pytest.mark.timeout(300)
def test_the_bundled_desktop_closure_omits_the_seed_and_session_import(shipped: set[str]):
    """Red when a dev-only module is kept (no switch-off) or forced in (an unguarded import of it)."""
    assert DEV_ONLY_MODULES & shipped == set()


def test_the_dev_only_modules_exist_so_their_absence_is_not_vacuous():
    from scripts.bundle_profile_closure import module_index

    assert DEV_ONLY_MODULES <= set(module_index())
