"""The lane's switch and its one writer: :func:`delta_patches_enabled` (with the
ROOT-config fault probe), :func:`emit_state_patch` — the ONE ``EventLog.append``
of a ``state.patched`` entry — and :func:`emit_scope_patch`, the one entity with
no projection.
"""

from __future__ import annotations

import logging
from typing import Any

from hermes_time import now

from ..config import AgentRuntimeConfig, load_root_runtime_config
from ..events import EventLog
from ..models import Event
from ..runtime_config import FALLBACK_DELTA_PATCHES, SHIPPED_DELTA_PATCHES
from ..serde import safe_id
from .models import (
    _UNRESOLVED,
    PATCH_OP_UPSERT,
    SCOPE_ENTITY,
    SCOPE_PATCH_ID,
    STATE_PATCHED_EVENT_TYPE,
)
from .payload import build_state_patch, normalize_correlation_id

__layer__ = "stores"

logger = logging.getLogger(__name__)


def _root_config_fault() -> tuple[str, str] | None:
    """``(what, detail)`` when the ROOT ``config.yaml`` is unreadable, else None.

    This exists because the loader CANNOT report the difference. Every
    ``agent_runtime`` config read goes through
    ``parse_cache.cached_yaml_file(path, default=None)``, and
    :func:`parse_cache.cached_by_mtime` returns that ``default`` for a loader
    exception just as it does for a missing file. So a ``config.yaml`` full of
    unparseable YAML does not raise out of
    :func:`config.load_root_runtime_config` — it silently produces an EMPTY
    config, and every key in it resolves to its shipped default.

    That is tolerable for a knob whose default is "off": absent and broken agree.
    It is NOT tolerable once a default ships ON, because the two cases stop
    agreeing and the loader answers the wrong one — a broken config would silently
    ACTIVATE a lane the operator may have written ``false`` for, in the very file
    the runtime just failed to read. Measured directly: before this probe existed,
    a root ``config.yaml`` containing invalid YAML resolved
    ``delta_patches_enabled()`` to ``True``, saying nothing.

    Absence is deliberately NOT a fault. A runtime root with no ``config.yaml``
    is a FRESH root — the case the shipped default is for — and it must resolve
    ON, silently.

    Cost on the happy path is zero: this hits the same ``(path, mtime, size)``
    cache entry ``load_agent_runtime_config`` is about to use.
    """

    from ..config import harness_root_config_path
    from ..parse_cache import cached_yaml_file

    try:
        path = harness_root_config_path()
        if not path.is_file():
            return None  # fresh root — the shipped default's whole purpose
        loaded = cached_yaml_file(path, default=_UNRESOLVED)
    except Exception as exc:  # resolving/statting the root is itself a fault
        return ("could not be examined", f"{type(exc).__name__}: {exc}")
    if loaded is _UNRESOLVED:
        return ("exists but did not parse", str(path))
    if loaded is not None and not isinstance(loaded, dict):
        return ("parsed to a non-mapping", f"{type(loaded).__name__} at {path}")
    return None


def delta_patches_enabled(config: AgentRuntimeConfig | None = None) -> bool:
    """Whether the S7-A producer lane is on (``read_model.delta_patches``).

    Shipped ON (:data:`runtime_config.SHIPPED_DELTA_PATCHES`) since 2026-08-14 —
    silence in the ROOT ``config.yaml`` resolves to the lane being LIVE, so a
    fresh clone against a fresh runtime root patches instead of re-shipping an
    822 KB core per field change. An operator's explicit ``false`` still wins:
    ``config._read_model_config`` falls back to the shipped default only for an
    ABSENT key.

    The flag is root-only, so ``config=None`` resolves through
    :func:`config.load_root_runtime_config` and never through the sticky-active
    profile. The three NON-OBSERVATIONS degrade to
    :data:`runtime_config.FALLBACK_DELTA_PATCHES` (off) rather than to the
    shipped default, and all three WARN:

    * the root ``config.yaml`` EXISTS but did not parse into a mapping — see
      :func:`_root_config_fault`, and read its header before trusting any other
      "config fault" reasoning in this module;
    * the load raised outright (``harness_root_config_path`` itself failing, an
      import error, …). A broken config must never take a store mutation down
      (observe-and-warn), and it must not be read as an instruction either;
    * the resolved config carries no ``read_model.delta_patches`` at all — which
      a real :class:`AgentRuntimeConfig` never does, only a stub or a
      partially-built object, i.e. the caller told us nothing.

    An ABSENT root config is NOT a fault — it is a fresh runtime root, the exact
    case the shipped default exists for, and it resolves ON.

    All three warn because an UNANNOUNCED off is the failure this default
    retires. The lane going dark is worth exactly one log line, and had one
    existed the 2026-08-13 misplacement would not have gone its whole life
    unnoticed.
    """

    cfg = config
    if cfg is None:
        fault = _root_config_fault()
        if fault is not None:
            logger.warning(
                "delta-patch lane OFF: the root runtime config %s (%s) — "
                "read_model.delta_patches ships on (%s), but a config the "
                "runtime cannot read is not an instruction; the stream falls "
                "back to full-core deltas until it parses",
                fault[0],
                fault[1],
                SHIPPED_DELTA_PATCHES,
            )
            return FALLBACK_DELTA_PATCHES
        try:
            cfg = load_root_runtime_config()
        except Exception as exc:
            logger.warning(
                "delta-patch lane OFF: could not load the root runtime config "
                "(%s: %s) — read_model.delta_patches ships on (%s); the stream "
                "falls back to full-core deltas until the config parses",
                type(exc).__name__,
                exc,
                SHIPPED_DELTA_PATCHES,
            )
            return FALLBACK_DELTA_PATCHES
    read_model = getattr(cfg, "read_model", None)
    resolved = getattr(read_model, "delta_patches", _UNRESOLVED)
    if resolved is _UNRESOLVED:
        logger.warning(
            "delta-patch lane OFF: the resolved runtime config carries no "
            "read_model.delta_patches (config object %s) — the stream falls "
            "back to full-core deltas",
            type(cfg).__name__,
        )
        return FALLBACK_DELTA_PATCHES
    return bool(resolved)


def emit_state_patch(
    event_log: EventLog,
    *,
    entity: str,
    entity_id: str,
    op: str = PATCH_OP_UPSERT,
    changed: dict[str, Any] | None = None,
    created: bool | None = None,
    correlation_id: str | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    persona_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Append one op-based ``state.patched`` entry, gated by
    ``read_model.delta_patches`` (shipped ON; flag off → no-op, provably inert).

    Returns True when an entry was appended, False when the flag is off or an
    ``upsert`` carried an empty ``changed``. Log-only: this appends to the
    EventLog; the stream promotes coverable batches to v2 ``patch`` frames.

    ``created`` is the additive lifecycle marker — see :func:`build_state_patch`.
    ``correlation_id`` is the gesture token, normalized HERE so no caller can put
    an illegal one on the wire (see :func:`normalize_correlation_id`).
    """

    if op == PATCH_OP_UPSERT and not changed:
        return False
    if not delta_patches_enabled(config):
        return False
    payload = build_state_patch(
        entity, entity_id, op, changed, created, normalize_correlation_id(correlation_id)
    )
    event_log.append(
        Event(
            ts=now(),
            type=STATE_PATCHED_EVENT_TYPE,
            task_id=task_id,
            run_id=run_id,
            persona_id=persona_id,
            payload=payload,
        )
    )
    return True


def emit_scope_patch(
    event_log: EventLog,
    *,
    active_workspace_id: Any,
    active_realm_id: Any,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """The ACTIVE-SCOPE patch: both pointers, always (WS1, plan §1.1).

    Emitted from inside ``WorkspaceStore.set_active`` / ``RealmStore.set_active``
    beside the ``workspace.activated`` / ``realm.activated`` domain event those
    writes already append — same chokepoint, same drain, so the two land in one
    coalesced batch and the event free-rides on this row's gate.

    **Op ``upsert``, not ``replace``.** The plan's stage row says ``replace``, and
    that op does not exist on this wire: :data:`FOLDABLE_PATCH_OPS` is
    ``{upsert, remove}`` and anything else demotes the batch it rides in — a
    ``replace`` would have shipped a patch nobody folds. What ``replace`` names is
    the SEMANTICS, and those are preserved without a new op because ``changed``
    always carries the complete row (:data:`SCOPE_PATCH_FIELDS`, both keys): a
    merge of every field of a two-field row IS a replace. Recorded here rather
    than silently corrected, because the plan's word is the one a reader will
    look for.

    ``None`` is a real value on both keys — "no workspace is active" is a state
    the store can be in (``harness workspace use --clear``), and it must reach the
    client as ``null`` rather than as an absent key, or a fold that skips missing
    keys would leave the departed pointer standing forever.
    """

    if not delta_patches_enabled(config):
        return False
    changed: dict[str, Any] = {
        "active_workspace_id": safe_id(active_workspace_id),
        "active_realm_id": safe_id(active_realm_id),
    }
    return emit_state_patch(
        event_log,
        entity=SCOPE_ENTITY,
        entity_id=SCOPE_PATCH_ID,
        op=PATCH_OP_UPSERT,
        changed=changed,
        correlation_id=correlation_id,
        config=config,
    )
