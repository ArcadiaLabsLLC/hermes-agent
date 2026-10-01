"""Verify the installation before opening an explicitly selected instance."""
from . import paths
from .gateway_identity import read_install_identity
from .persona_assignments import PersonaInstanceStore
from .workspace_scope import effective_workspace_id

__layer__ = "stores"


class InstanceSelectionError(ValueError):
    pass


def verify_instance_install(params):
    if "install_id" not in params:
        return
    expected = params["install_id"]
    if not isinstance(expected, str) or not expected.strip():
        raise InstanceSelectionError("installation_required")
    if read_install_identity(paths.store_root()).install_id != expected:
        raise InstanceSelectionError("installation_changed")


def opened_instance_identity(row, install_id):
    instance = PersonaInstanceStore().get(row["persona_instance_id"])
    return {"install_id": install_id,
            "workspace_id": effective_workspace_id(instance, active_workspace_id=None)}
