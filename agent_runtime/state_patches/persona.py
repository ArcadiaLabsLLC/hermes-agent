"""The persona lane: the ``persona`` patch every ``persona.updated`` rides beside.

Row RT-FU-ADDING-AN-AGENT-SENDS-EVERY-OPEN-ETERNIA-A-FULL-REFRESH (review
w1118a.63 D2, 2026-11-20). Since 03a63a0010 an agent create writes a persona
record of its own, and the ``persona.updated`` that write appended was
uncovered, so every add demoted its batch to a full core for every subscriber.

**Never covered bare** (the ``chat_opened`` lesson in ``patch_coverage``).
Eternia reads the persona-catalog row a create adds to the core's ``agents``
list: the library's Local list is built from it and the roster's readiness join
keys on it. A covered event with no pair would leave that row off every
connected client. So EVERY ``persona.updated`` goes through
:func:`emit_persona_updated`, which appends its paired ``persona`` patch first:

* the FIRST write of an agent copy's record (the create) — a complete-row
  ``upsert`` stamped ``created: true``, projected by the core's own builder
  (``snapshot.summaries._agent_summary``) so the two cannot drift; all or
  nothing, like :func:`~.persona_instance.emit_persona_instance_create`;
* every other write, and every departure — an honest ``refresh``. A persona
  edit moves rows the catalog row cannot carry (every instance row derives its
  model and skills from its persona; a template persona moves
  ``available_personas``), and a ``refresh`` is never foldable, so those
  batches keep the full core they always had.

THE DERIVABILITY AUDIT for the create. Writing a copy's first record moves, in
the core: its ``agents`` row (the patch is that row); ``available_personas``
not at all (a copy's profile is no template, ``persona_lifecycle.is_agent_copy``);
no instance row (the create's instance is added after the record, and carries
its own create patch). Read off the regenerated create pair (narrow core vs
the core before), the residue a folding client holds stale until its next core
is three fields with no Eternia reader: ``migration.counts.agents`` (+1), the
TEMP ``runtime_paths_diagnostic.profiles_root_entries`` (the new profile's
folder) and ``prompt_observability``'s per-persona telemetry — the last the
same accepted residue the ``scope`` patch names.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import AgentRuntimeConfig
from ..events import EventLog
from ..models import EVENT_PAYLOAD_LIMIT_BYTES
from ..store_events import emit_store_event
from .emit import delta_patches_enabled, emit_state_patch
from .models import PATCH_OP_REFRESH, PATCH_OP_UPSERT, PERSONA_ENTITY
from .payload import _is_oversize_marker, build_state_patch

__layer__ = "stores"

logger = logging.getLogger(__name__)

PERSONA_UPDATED_EVENT_TYPE = "persona.updated"


def project_persona_wire_row(persona: Any) -> dict[str, Any]:
    """The persona's COMPLETE ``agents`` row, built by the core's own builder.

    ``snapshot.sections`` builds the row as
    ``_agent_summary(agent, include_tool_details=True, readiness=...)`` with the
    readiness walk run inside ``runtime_environment_status_scope``; this is that
    call, so a field added to the summary reaches the patch in the same commit.
    """

    from hermes_cli.runtime_environment import runtime_environment_status_scope

    from ..profile_readiness import profile_readiness_for_persona
    from ..snapshot.summaries import _agent_summary

    with runtime_environment_status_scope():
        readiness = profile_readiness_for_persona(persona)
    return _agent_summary(persona, include_tool_details=True, readiness=readiness)


def persona_create_is_foldable(persona: Any) -> bool:
    """Whether a first write of ``persona`` moves only its own ``agents`` row.

    An agent copy only: a template persona's first write also adds a placeable
    ``available_personas`` row. And only a persona the core lists at all
    (``is_runtime_persona``) — a row the core does not carry must not be inserted.
    """

    from ..persona_lifecycle import is_agent_copy, is_runtime_persona

    return is_agent_copy(persona) and is_runtime_persona(persona)


def _create_row(persona: Any) -> dict[str, Any] | None:
    """The create's lossless ``upsert`` row, or ``None`` when it must degrade to a refresh."""

    row = project_persona_wire_row(persona)
    payload = build_state_patch(PERSONA_ENTITY, persona.id, PATCH_OP_UPSERT, row, True)
    lossless = payload.get("op") == PATCH_OP_UPSERT and not any(
        _is_oversize_marker(value) for value in (payload.get("changed") or {}).values()
    )
    if not lossless:
        logger.warning(
            "persona create patch degraded to refresh: the row for %s does not fit "
            "the %d-byte payload cap losslessly — the batch takes a full core",
            persona.id,
            EVENT_PAYLOAD_LIMIT_BYTES,
        )
        return None
    return row


def _emit_persona_refresh(
    event_log: EventLog, persona_id: str, config: AgentRuntimeConfig | None
) -> bool:
    return emit_state_patch(
        event_log,
        entity=PERSONA_ENTITY,
        entity_id=persona_id,
        op=PATCH_OP_REFRESH,
        persona_id=persona_id,
        config=config,
    )


class PreparedPersonaUpdated:
    """A ``persona.updated`` and its paired patch, projected and ready to append.

    Row RT-FU-ADDING-AN-AGENT-CAN-STILL-SEND-A-FULL-REFRESH-FROM-A-SCOPE-RECONCILE
    (seen on a fixture serve 2026-11-20, lane w1118a-hrt6): the create's row is a
    readiness walk that took 3-5 s cold (0.5 s warm on the live serve). Projected
    AFTER the record landed, the agents-directory file sat in the stream
    watchdog's ``scope`` fingerprint that long with no event beside it, and a
    heartbeat in that gap reconciled it as an uncovered ``scope`` move — a full
    core for every subscriber (2 of 4 adds). So the writer projects FIRST
    (:func:`prepare_persona_updated`), then writes, then calls :meth:`emit`, which
    only appends: the record and its two events land back to back.
    """

    __slots__ = ("_config", "_display_name", "_patch", "_persona_id", "_row")

    def __init__(
        self,
        persona_id: str,
        display_name: str | None,
        patch: str | None,
        row: dict[str, Any] | None,
        config: AgentRuntimeConfig | None,
    ) -> None:
        self._persona_id = persona_id
        self._display_name = display_name
        #: ``None`` (patches off), ``PATCH_OP_UPSERT`` (``row`` set) or ``PATCH_OP_REFRESH``.
        self._patch = patch
        self._row = row
        self._config = config

    def emit(self, event_log: EventLog) -> None:
        """Append the paired patch, then the event. No projection happens here."""

        try:
            if self._patch == PATCH_OP_UPSERT:
                emit_state_patch(
                    event_log,
                    entity=PERSONA_ENTITY,
                    entity_id=self._persona_id,
                    op=PATCH_OP_UPSERT,
                    changed=self._row,
                    created=True,
                    persona_id=self._persona_id,
                    config=self._config,
                )
            elif self._patch == PATCH_OP_REFRESH:
                _emit_persona_refresh(event_log, self._persona_id, self._config)
        except Exception:
            logger.warning("persona patch append failed: %s", self._persona_id, exc_info=True)
        emit_store_event(
            event_log,
            PERSONA_UPDATED_EVENT_TYPE,
            {"persona_id": self._persona_id, "display_name": self._display_name},
            domain="store",
        )


def prepare_persona_updated(
    *,
    persona_id: str,
    display_name: str | None,
    created: Any = None,
    config: AgentRuntimeConfig | None = None,
) -> PreparedPersonaUpdated:
    """Project the ``persona.updated`` pair now; append it later with ``emit``.

    ``created`` is the persona as it will read back after its FIRST write (its
    record did not exist); anything else — an edit, a departure — is ``None`` and
    pairs with a ``refresh``. The patch is best effort like the event
    (``emit_store_event``): a failed projection degrades to a ``refresh``, never
    to a bare event.
    """

    try:
        if not delta_patches_enabled(config):
            patch, row = None, None
        elif created is not None and persona_create_is_foldable(created):
            try:
                row = _create_row(created)
            except Exception:
                logger.warning("persona create patch failed; emitting a refresh", exc_info=True)
                row = None
            patch = PATCH_OP_UPSERT if row is not None else PATCH_OP_REFRESH
        else:
            patch, row = PATCH_OP_REFRESH, None
    except Exception:
        logger.warning("persona patch projection failed: %s", persona_id, exc_info=True)
        patch, row = PATCH_OP_REFRESH, None
    return PreparedPersonaUpdated(persona_id, display_name, patch, row, config)


def emit_persona_updated(
    event_log: EventLog,
    *,
    persona_id: str,
    display_name: str | None,
    created: Any = None,
    config: AgentRuntimeConfig | None = None,
) -> None:
    """Append ``persona.updated`` and, first, the ``persona`` patch it pairs with.

    For a departure or an edit whose write has already landed. A writer that
    creates a record projects before writing instead (:func:`prepare_persona_updated`).
    MUTATION: emit the event without its pair and
    ``test_every_persona_updated_rides_beside_its_persona_patch`` reddens.
    """

    prepare_persona_updated(
        persona_id=persona_id, display_name=display_name, created=created, config=config
    ).emit(event_log)
