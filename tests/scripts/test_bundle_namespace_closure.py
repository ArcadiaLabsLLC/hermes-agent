"""The bundled-desktop closure carries the namespace machinery (row RT-NAMESPACE-IN-BUNDLE-CLOSURE).

Players run the bundled edition, never the Developer Edition (owner 2026-10-19, plan §2.7): a
bundle without the resolver ignores ``HERMES_NAMESPACE`` and every launcher profile writes the base
root, and without ``hermes namespace probe`` the launcher's pre-spawn check cannot tell. The proof is
the packager's own import walk (``scripts/bundle_profile_closure.py::profile_walk``) over the real
profile — what the bundle ships — not a read of the YAML.
"""

from __future__ import annotations

import pytest

from agent_runtime.bundle_profiles.manifest import load_profile
from scripts.bundle_profile_closure import profile_walk

NAMESPACE_MODULES = {
    "hermes_cli._namespace_bootstrap",  # the resolver main.py runs before any hermes import
    "hermes_cli.namespace_cmd",  # `hermes namespace probe | list | seed | reset | delete`
    "agent_runtime.namespace",  # the store-root isolation gate
    "agent_runtime.namespace_admin",  # the admin verbs
}


@pytest.mark.timeout(300)  # the desktop walk (~65 s cold, like the phone walk's ~40 s)
def test_the_bundled_desktop_closure_ships_the_namespace_machinery():
    walk, _index = profile_walk(load_profile("bundled-desktop"), parents=True)
    kept = set(walk.kept)
    assert "hermes_cli.main" in kept  # positive control: the walk reached the serve entry
    assert NAMESPACE_MODULES - kept == set()
