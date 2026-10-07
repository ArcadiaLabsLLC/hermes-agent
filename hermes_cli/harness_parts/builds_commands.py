"""``hermes harness builds``: the announced-build registry's operator door.

``registry-path`` answers a writer started by hand (the launcher's ``prebuild.dart`` from
an orchestrator shell) where to announce, when it did not inherit
``HERMES_BUILD_REGISTRY_DIR`` from serve (plan
``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §2, owner call 6).
It holds no rule of its own: the directory is ``agent_runtime.builds.registry``'s.
"""

from __future__ import annotations

from hermes_cli.harness_support import _object_envelope, _print_stage42

__layer__ = "lanes"
__all__ = ["_cmd_builds_registry_path"]


def _cmd_builds_registry_path(args) -> int:
    from agent_runtime.root_observability import attach_root_observability
    from agent_runtime.builds.registry import registry_dir
    from agent_runtime.builds.vocabulary import REGISTRY_DIR_ENV, REGISTRY_SCHEMA_VERSION

    payload = {
        "registry_dir": str(registry_dir()),
        "env": REGISTRY_DIR_ENV,
        "schema_version": REGISTRY_SCHEMA_VERSION,
    }
    _print_stage42(attach_root_observability(_object_envelope("build_registry_path", payload)), args=args, default_output="json")
    return 0
