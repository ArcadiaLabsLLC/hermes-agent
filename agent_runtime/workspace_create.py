"""Workspace creation — ONE implementation, two doors.

``harness workspace create`` (argv) and ``runtime.workspace.create`` (the method
lane) are the same operation reached two ways, so the decision lives here and
both doors call it: :func:`plan_workspace_create` resolves the request (realm,
template, copy scopes, the template's roster/settings under explicit overrides)
without writing anything, and :func:`apply_workspace_create` performs it —
store create, realm join, template content copy, activation inside the ACTIVE
realm — and renders the argv verb's row.

The method door adds one thing on top, :func:`create_workspace`: a receipt that
fences replay of one idempotency key. The receipt is written only after the plan
resolved, so a refused request (unknown realm, unknown template) never burns
its key into ``workspace_creation_unresolved``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from . import paths
from .errors import NotFound
from .locks import workspace_create_lock
from .office_store import OfficeStore
from .scope_activation import workspace_row
from .serde import read_json, write_json_atomic
from .store import RealmStore, WorkspaceStore
from .workspace_template import COPY_SCOPES, CONTENT_COPY_SCOPES, copy_workspace_content, normalize_copy_scopes

__layer__ = "lanes"


class WorkspaceCreationReason(StrEnum):
    INVALID = "invalid_workspace_creation"
    CONFLICT = "idempotency_conflict"
    UNRESOLVED = "workspace_creation_unresolved"
    ARCHIVED = "workspace_archived"
    REALM_NOT_FOUND = "realm_not_found"
    TEMPLATE_NOT_FOUND = "template_workspace_not_found"


class WorkspaceCreationRefused(ValueError):
    def __init__(self, reason: WorkspaceCreationReason):
        self.reason = reason
        super().__init__(reason.value)


class TemplateWorkspaceNotFound(NotFound):
    """The ``--from-workspace`` / ``template_workspace_id`` does not resolve."""


@dataclass(frozen=True)
class WorkspaceCreatePlan:
    name: str
    realm_id: str | None
    template: Any  # Workspace | None
    scopes: tuple[str, ...]
    agent_ids: tuple[str, ...]
    blueprint: str | None
    isolation: str | None
    max_lanes: int | None


def plan_workspace_create(
    name: str,
    *,
    realm_id: str | None = None,
    template_workspace_id: str | None = None,
    copy_scopes: list[str] | tuple[str, ...] | None = None,
    agent_ids: list[str] | tuple[str, ...] = (),
    blueprint: str | None = None,
    isolation: str | None = None,
    max_lanes: int | None = None,
    check_realm: bool = True,
) -> WorkspaceCreatePlan:
    """Resolve a create request without writing. Raises ``NotFound`` for an
    unknown realm and :class:`TemplateWorkspaceNotFound` for an unknown template;
    copy scopes without a template are a ``ValueError``."""
    template = None
    scopes: tuple[str, ...] = ()
    if template_workspace_id:
        try:
            template = WorkspaceStore().get(template_workspace_id)
        except NotFound as exc:
            raise TemplateWorkspaceNotFound(str(exc)) from None
        scopes = normalize_copy_scopes(list(copy_scopes) if copy_scopes else None)
    elif copy_scopes:
        raise ValueError("--copy requires --from-workspace")
    if realm_id and check_realm:
        RealmStore().get(realm_id)
    # Template settings/roster feed the create itself; explicit values always
    # win over the template so the operator can override any copied field.
    agents = list(agent_ids)
    if template is not None:
        if "agents" in scopes and not agents:
            agents = list(template.agent_ids or [])
        if "settings" in scopes:
            blueprint = template.default_blueprint_id if blueprint is None else blueprint
            isolation = template.isolation if isolation is None else isolation
            max_lanes = template.max_concurrent_lanes if max_lanes is None else max_lanes
    return WorkspaceCreatePlan(name, realm_id, template, scopes, tuple(agents), blueprint, isolation, max_lanes)


def apply_workspace_create(plan: WorkspaceCreatePlan, *, workspace_id: str | None = None):
    """Perform a resolved plan. Returns ``(workspace, row, warnings)``."""
    store = WorkspaceStore()
    item = store.create(
        name=plan.name,
        agent_ids=list(plan.agent_ids),
        default_blueprint_id=plan.blueprint,
        isolation=plan.isolation or "soft",
        max_concurrent_lanes=plan.max_lanes,
        realm_id=plan.realm_id,
        workspace_id=workspace_id,
    )
    _join_realm(item)
    # Office/board content copies AFTER the workspace exists, through the
    # store chokepoints, so every copied artifact rides its contract event.
    warnings: list[dict] = []
    copied = None
    if plan.template is not None:
        content_scopes = tuple(scope for scope in plan.scopes if scope in CONTENT_COPY_SCOPES)
        if content_scopes:
            outcome = copy_workspace_content(plan.template.id, item.id, scopes=content_scopes)
            copied = outcome["copied"]
            warnings.extend(outcome["warnings"])
    # A workspace created inside the ACTIVE realm becomes active immediately —
    # the operator expects to land in the workspace they just created.
    # (workspace.created / workspace.activated are emitted by the store.)
    if item.realm_id and item.realm_id == RealmStore().active_id():
        store.set_active(item.id)
    return item, _row(item, plan, copied), warnings


def _join_realm(item) -> None:
    if not item.realm_id:
        return
    realm = RealmStore().get(item.realm_id)
    if item.id not in realm.workspace_ids:
        realm.workspace_ids.append(item.id)
        RealmStore().save(realm)


def _row(item, plan: WorkspaceCreatePlan, copied) -> dict:
    row = workspace_row(item)
    if plan.template is not None:
        row["template_workspace_id"] = plan.template.id
        row["copy_scopes"] = list(plan.scopes)
        if copied is not None:
            row["copied"] = copied
    return row


def conversations_workspace():
    """One native home for non-spatial conversations; never moves an agent."""
    return create_workspace("Conversations", "harness:conversations-workspace:v1")[0]


def _valid_request(name, key, realm_id, template_workspace_id, copy_scopes) -> bool:
    if (not isinstance(name, str) or not name.strip() or len(name) > 120 or
            any(ord(c) < 32 for c in name) or not isinstance(key, str) or not 1 <= len(key) <= 128):
        return False
    for value in (realm_id, template_workspace_id):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            return False
    if copy_scopes is not None:
        if not isinstance(copy_scopes, list) or any(scope not in COPY_SCOPES for scope in copy_scopes):
            return False
        if copy_scopes and template_workspace_id is None:
            return False
    return True


def _fingerprint(name, realm_id, template_workspace_id, copy_scopes) -> str:
    # A name-only request keeps the original name-only fingerprint so receipts
    # written before the widening (the conversations workspace) still replay.
    if realm_id is None and template_workspace_id is None and copy_scopes is None:
        return hashlib.sha256(name.encode()).hexdigest()
    canonical = json.dumps(
        {"name": name, "realm_id": realm_id, "template_workspace_id": template_workspace_id,
         "copy_scopes": copy_scopes}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_workspace(
    name: str,
    key: str,
    *,
    realm_id: str | None = None,
    template_workspace_id: str | None = None,
    copy_scopes: list[str] | None = None,
):
    """The method door: a receipt fences replay; the workspace record remains
    the sole authority. Returns ``(workspace, row, warnings)``."""
    if not _valid_request(name, key, realm_id, template_workspace_id, copy_scopes):
        raise WorkspaceCreationRefused(WorkspaceCreationReason.INVALID)
    name = name.strip()
    digest = hashlib.sha256(key.encode()).hexdigest()
    fingerprint = _fingerprint(name, realm_id, template_workspace_id, copy_scopes)
    identity = "ws_" + digest[:32]
    receipt_path = paths.store_root() / "workspace_creates" / f"{digest}.json"
    store = WorkspaceStore()
    with workspace_create_lock(digest):
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if receipt != {"workspace_id": identity, "fingerprint": fingerprint}:
                raise WorkspaceCreationRefused(WorkspaceCreationReason.CONFLICT)
            try:
                existing = store.get(identity)
            except NotFound:
                # A crash before create or a later deletion is not permission to recreate.
                raise WorkspaceCreationRefused(WorkspaceCreationReason.UNRESOLVED) from None
            if existing.archived:
                raise WorkspaceCreationRefused(WorkspaceCreationReason.ARCHIVED)
            # A replay heals a realm join a crash interrupted; it never re-copies
            # template content and never re-activates (that was the first call's).
            _join_realm(existing)
            OfficeStore().ensure_surface(identity)
            row = workspace_row(existing)
            if template_workspace_id is not None:
                row["template_workspace_id"] = template_workspace_id
                row["copy_scopes"] = list(normalize_copy_scopes(copy_scopes))
            return existing, row, []
        try:
            plan = plan_workspace_create(
                name, realm_id=realm_id, template_workspace_id=template_workspace_id, copy_scopes=copy_scopes)
        except TemplateWorkspaceNotFound:
            raise WorkspaceCreationRefused(WorkspaceCreationReason.TEMPLATE_NOT_FOUND) from None
        except NotFound:
            raise WorkspaceCreationRefused(WorkspaceCreationReason.REALM_NOT_FOUND) from None
        write_json_atomic(receipt_path, {"workspace_id": identity, "fingerprint": fingerprint})
        created, row, warnings = apply_workspace_create(plan, workspace_id=identity)
        OfficeStore().ensure_surface(identity)
        return created, row, warnings
