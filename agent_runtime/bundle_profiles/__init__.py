"""Bundle profiles: one manifest per Hermes distribution (bundled desktop today, phone later).

``manifest``    loads/validates ``<profile>.yaml`` and applies it through Hermes's
                existing switches (``agent.disabled_toolsets``, config keys, env).
``route_gate``  refuses the profile's switched-off upstream dashboard routes.

The import closure the packaging step bundles is ``scripts/bundle_profile_closure.py``.
"""

from agent_runtime.bundle_profiles.manifest import (
    ProfileManifest,
    ProfileManifestError,
    apply_to_config,
    load_profile,
    process_environment,
)

__layer__ = "policy"

__all__ = [
    "ProfileManifest",
    "ProfileManifestError",
    "apply_to_config",
    "load_profile",
    "process_environment",
]
