"""JSON-RPC registration for ``runtime.local_llama.*``; the manager binding is ``binding.py``."""
from __future__ import annotations

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ

from .binding import get_manager
from .config import LocalLlamaError, identifier

METHODS = {"status": TIER_READ, "config.get": TIER_CONSOLE, "config.set": TIER_CONSOLE,
           "catalog.scan": TIER_CONSOLE, "start": TIER_CONSOLE, "stop": TIER_CONSOLE,
           "load": TIER_CONSOLE, "unload": TIER_CONSOLE, "logs.get": TIER_CONSOLE}
GUARDS = {"request_id", "expect_epoch", "expect_revision", "expect_config_revision"}
SETUP_FIELDS = {
    "setup.capabilities": set(), "setup.status": {"request_id", "operation_id"},
    "installations.detect": set(), "installations.validate": {"executable_path"},
    "host_paths.validate": {"path", "purpose"}, "hardware.get": set(), "releases.list": set(),
    "installation.plan": {"tag", "release_id", "variant_id", "destination_parent"},
    "installation.apply": GUARDS | {"plan_id", "plan_revision", "acknowledged_warning_ids"},
    "installations.activate": GUARDS | {"installation_id", "validation_token", "expect_inventory_revision"},
    "operations.cancel": {"request_id", "operation_id"},
}


def _lifecycle(operation, params):
    manager = get_manager()
    if operation == "status":
        return manager.status(operation_id=params.get("operation_id"), request_id=params.get("request_id"))
    if operation == "config.get":
        return manager.config_get()
    if operation == "logs.get":
        return manager.logs_get(cursor=params.get("cursor"), limit=params.get("limit", 100))
    return manager.submit(operation, params)


def _setup(operation, params):
    if not isinstance(params, dict) or set(params) - SETUP_FIELDS[operation]:
        raise LocalLlamaError("invalid_parameter", "Unknown setup parameters")
    setup = get_manager().setup
    simple = {"setup.capabilities": setup.capabilities, "installations.detect": setup.detect,
              "hardware.get": setup.hardware, "releases.list": setup.releases}
    if operation in simple:
        return simple[operation]()
    if operation == "setup.status":
        return setup.status(**params)
    if operation == "installations.validate":
        return setup.validate(params.get("executable_path"))
    if operation == "host_paths.validate":
        return setup.paths(params.get("path"), params.get("purpose"))
    if operation == "installation.plan":
        return setup.plan(params)
    if operation == "operations.cancel":
        identifier(params.get("request_id"), "request_id")
        return setup.cancel(params.get("operation_id"), params.get("request_id"))
    return setup.submit("install" if operation == "installation.apply" else "activate", params)


def register(method, ok, err):
    verbs = [(suffix, tier, _lifecycle) for suffix, tier in METHODS.items()]
    verbs += [(suffix, TIER_READ if suffix == "setup.capabilities" else TIER_CONSOLE, _setup) for suffix in SETUP_FIELDS]
    for suffix, tier, dispatch in verbs:
        def handler(rid, params, context, operation=suffix, dispatch=dispatch):
            try:
                return ok(rid, dispatch(operation, params))
            except LocalLlamaError as exc:
                return err(rid, exc.code, str(exc), {"reason": exc.reason, **exc.details})
            except (OSError, ValueError, TypeError, KeyError):
                if dispatch is _lifecycle:
                    raise
                return err(rid, -32000, "Setup could not complete; check the host path and connection", {"reason": "setup_unavailable"})
        method("runtime.local_llama." + suffix, tier=tier)(handler)
