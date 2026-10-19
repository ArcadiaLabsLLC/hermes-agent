"""The runtime half of profile namespaces: the store-root isolation assertion.

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.1, §4 H1. The resolver itself (ids, layout, the CLI pre-parse) is
``hermes_cli/_namespace_bootstrap.py`` — stdlib only, because it runs before any hermes module is
importable; this module re-exports what the runtime needs from it.

:func:`assert_namespace_isolation` sits beside ``resolution.assert_probe_isolation`` in
``paths.store_root``: while a namespace is named, every resolved store root, home and head home
must lie INSIDE that namespace — a path in the base root, in another namespace, or anywhere else
raises :class:`NamespaceIsolationViolation` before any store I/O. Unset (or ``base``) it is one
dict lookup and returns.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from hermes_cli._namespace_bootstrap import (
    BASE_ID,
    ENV,
    Layout,
    NamespaceRefused,
    Reason,
    layout,
    namespace_stamp,
    validate_id,
)

from .errors import AgentRuntimeError

__layer__ = "models"

__all__ = [
    "BASE_ID",
    "ENV",
    "Layout",
    "NamespaceIsolationViolation",
    "NamespaceRefused",
    "Reason",
    "assert_namespace_isolation",
    "layout",
    "namespace_named",
    "namespace_stamp",
    "validate_id",
]

_VERIFIED: set[tuple[Any, ...]] = set()


class NamespaceIsolationViolation(AgentRuntimeError):
    """A namespaced process resolved a path outside its own namespace."""

    code = "namespace_isolation"

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def namespace_named(env: Mapping[str, str] | None = None) -> bool:
    """True while this process runs in a namespace (``HERMES_NAMESPACE`` set and not ``base``)."""
    return namespace_stamp(env) != ""


def assert_namespace_isolation(resolution: Any, *, env: Mapping[str, str] | None = None) -> None:
    """Fail fast when a namespaced process would resolve a store/home path outside its namespace."""
    source = os.environ if env is None else env
    ns_id = namespace_stamp(source)
    if not ns_id:
        return
    head = str(source.get("HERMES_HEAD_HOME") or "").strip() or None
    checked = (("store_root", resolution.store_root), ("HERMES_HOME", resolution.hermes_home), ("HERMES_HEAD_HOME", head))
    key = (ns_id, *(str(source.get(k) or "") for k in ("HERMES_DEPENDENCY_ROOT", "HERMES_NAMESPACES_DIR", "HERMES_HOME",
                                                       "LOCALAPPDATA")), *(str(v) for _, v in checked))
    if key in _VERIFIED:
        return
    try:
        item = layout(ns_id, source)
    except NamespaceRefused as exc:
        raise NamespaceIsolationViolation(exc.reason.value, exc.detail) from exc
    for label, path in checked:
        if path is None:
            continue
        where = item.classify(path)
        if where != "own":
            raise NamespaceIsolationViolation(
                Reason.ISOLATION.value,
                f"{label} {path} lies in {where}; namespace {ns_id!r} may only resolve paths inside {item.root}",
            )
    _VERIFIED.add(key)
