"""Installer methods share the existing authenticated, install-aimed dispatcher."""
from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from .config import LocalLlamaError, identifier
from .service import get_manager

GUARDS = {"request_id", "expect_epoch", "expect_revision", "expect_config_revision"}
FIELDS = {
    "setup.capabilities": set(), "setup.status": {"request_id", "operation_id"},
    "installations.detect": set(), "installations.validate": {"executable_path"},
    "host_paths.validate": {"path", "purpose"}, "hardware.get": set(), "releases.list": set(),
    "installation.plan": {"tag", "release_id", "variant_id", "destination_parent"},
    "installation.apply": GUARDS | {"plan_id", "plan_revision", "acknowledged_warning_ids"},
    "installations.activate": GUARDS | {"installation_id", "validation_token", "expect_inventory_revision"},
    "operations.cancel": {"request_id", "operation_id"},
}


def register(method, ok, err):
    for suffix, allowed in FIELDS.items():
        def handler(rid, params, context, operation=suffix, fields=allowed):
            try:
                if not isinstance(params, dict) or set(params) - fields:
                    raise LocalLlamaError("invalid_parameter", "Unknown setup parameters")
                setup = get_manager().setup
                if operation == "setup.capabilities":
                    result = setup.capabilities()
                elif operation == "setup.status":
                    result = setup.status(**params)
                elif operation == "installations.detect":
                    result = setup.detect()
                elif operation == "installations.validate":
                    result = setup.validate(params.get("executable_path"))
                elif operation == "host_paths.validate":
                    result = setup.paths(params.get("path"), params.get("purpose"))
                elif operation == "hardware.get":
                    result = setup.hardware()
                elif operation == "releases.list":
                    result = setup.releases()
                elif operation == "installation.plan":
                    result = setup.plan(params)
                elif operation == "operations.cancel":
                    identifier(params.get("request_id"), "request_id")
                    result = setup.cancel(params.get("operation_id"), params.get("request_id"))
                else:
                    result = setup.submit("install" if operation == "installation.apply" else "activate", params)
                return ok(rid, result)
            except LocalLlamaError as exc:
                return err(rid, exc.code, str(exc), {"reason": exc.reason, **exc.details})
            except (OSError, ValueError, TypeError, KeyError):
                return err(rid, -32000, "Setup could not complete; check the host path and connection", {"reason": "setup_unavailable"})
        method("runtime.local_llama." + suffix, tier=TIER_READ if suffix == "setup.capabilities" else TIER_CONSOLE)(handler)
