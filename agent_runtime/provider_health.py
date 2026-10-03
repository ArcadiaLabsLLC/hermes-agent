from __future__ import annotations

import sys
from typing import Any

from hermes_constants import get_hermes_home
from hermes_cli.runtime_environment import required_packages_for, runtime_environment_status

from . import paths
from .models import AgentPersona
from .profile_context import active_profile_name

__layer__ = "stores"


def provider_health_for_personas(personas: list[AgentPersona]) -> dict[str, Any]:
    """Return compact redaction-safe runtime/provider dependency health.

    This proves the exact interpreter running Harness can import the provider
    client dependencies before a live persona tick spends tokens. It intentionally
    reports paths to local interpreter/runtime roots, but never env dumps,
    credentials, provider config bodies, or tokens.
    """
    packages: list[str] = []
    for persona in personas:
        for package in required_packages_for(
            provider=getattr(persona, "provider", None),
            api_mode=getattr(persona, "api_mode", None),
            model=getattr(persona, "model", None),
        ):
            if package not in packages:
                packages.append(package)
    env = runtime_environment_status(packages)
    issues = list(env.issues)
    return {
        "ok": not issues,
        "interpreter": env.executable,
        "runtime_root": str(paths.store_root()),
        "hermes_home": str(get_hermes_home()),
        "hermes_profile": active_profile_name(),
        "required_packages": packages,
        "package_available": env.package_available,
        "issues": issues,
    }


def runtime_health() -> dict[str, Any]:
    """The ``harness health`` block — ONE implementation, two doors.

    ``harness health --json`` prints it and ``runtime.health`` (the method lane)
    returns it, so the launcher's start-up and Connections probes can read the
    same block over the running serve instead of paying a cold ``harness
    status`` (a ~3 MB projection) for the one key they read. It is the roster
    this runtime would tick, with every persisted persona, checked against the
    interpreter running it — the ``runtime_health`` key ``harness status`` also
    carries, computed the same way.
    """
    from .config import ensure_persisted_personas, load_agent_runtime_config

    return provider_health_for_personas(ensure_persisted_personas(load_agent_runtime_config()))


def provider_health_for_persona(persona: AgentPersona) -> dict[str, Any]:
    return provider_health_for_personas([persona])


def assert_provider_health_for_persona(persona: AgentPersona) -> None:
    health = provider_health_for_persona(persona)
    if health["ok"]:
        return
    issue_bits = []
    for issue in health["issues"]:
        package = issue.get("package") or "runtime dependency"
        kind = issue.get("kind") or "runtime_dependency_missing"
        issue_bits.append(f"{kind}:{package}")
    detail = ", ".join(issue_bits) or "runtime dependency issue"
    raise ImportError(f"Harness provider dependency preflight failed before token spend: {detail}; interpreter={sys.executable}")
