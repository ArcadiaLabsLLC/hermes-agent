"""JSON-RPC registration and the serve-owned binding (only the socket owner builds a manager)."""
from __future__ import annotations

from pathlib import Path
import threading

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ

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

_lock = threading.RLock()
_bindings = {}


def bind(root: Path, config_path: Path):
    with _lock:
        _bindings.setdefault(str(root.resolve()), {"root": root, "config": config_path, "manager": None})


def get_manager(*, root=None, create=True):
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.paths import store_root
    from .manager import LocalLlamaManager
    key = str(Path(root).resolve() if root is not None else store_root().resolve())
    with _lock:
        binding = _bindings.get(key)
        if binding is None:
            raise LocalLlamaError("manager_unavailable", "Connect to the owning Hermes service to manage local llama", code=-32000)
        if binding["manager"] is None:
            if not create:
                raise LocalLlamaError("model_not_ready", "Turn on llama and load the selected model", code=4090)
            identity = ensure_install_identity(binding["root"])
            if not identity.install_id:
                raise LocalLlamaError("manager_unavailable", "Hermes installation identity is unavailable", code=-32000)
            binding["manager"] = LocalLlamaManager(binding["root"], binding["config"], identity.install_id)
        return binding["manager"]


def shutdown(*, root=None):
    with _lock:
        if root is None:
            bindings = list(_bindings.values())
            _bindings.clear()
        else:
            binding = _bindings.pop(str(Path(root).resolve()), None)
            bindings = [binding] if binding else []
    for binding in bindings:
        if binding["manager"] is not None:
            binding["manager"].close()


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
