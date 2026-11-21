"""``plugins/eternia-harness/dashboard``'s door: the three runtime names the harness dashboard routes use.

Its own module, not ``harness.py``: the dashboard is a ``stores``-layer module, and a door may sit no
higher than its importer (W0-G6), while the plugin's door is ``wiring``. The fork names are ``stores`` or
lower, imported plainly so the layer gate checks them; upstream's ``hermes_cli.profiles`` names are read at
call time (a module ``__getattr__``), as the route's own import did, so a profile
store replaced on that module is the one the route asks. Published in ``hermes_cli/data/plugin_api_fork.json``.
"""

from __future__ import annotations

from agent_runtime.blueprints.resolve import promote_profile_to_persona
from agent_runtime.bundle_profiles.model_downloads import gate_model_download_routes

__layer__ = "stores"
__all__ = ["gate_model_download_routes", "normalize_profile_name", "profile_exists", "promote_profile_to_persona"]
_PROFILE_NAMES = frozenset({"normalize_profile_name", "profile_exists"})


def __getattr__(name: str):
    if name not in _PROFILE_NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from hermes_cli import profiles

    return getattr(profiles, name)
