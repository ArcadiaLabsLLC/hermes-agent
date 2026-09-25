"""Per-instance detail reads: the persona session DB scope, an agent's tool
detail and ``persona_instance_detail_for_id``.
"""

from __future__ import annotations

from contextlib import contextmanager

from agent_runtime.events import CachedEventLog
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.store import AgentStore
from agent_runtime.tool_visibility import resolve_tool_visibility

from agent_runtime.snapshot.context import logger

__layer__ = "lanes"

__all__ = [
    "_agent_tool_detail",
    "_default_persona_session_db",
    "persona_instance_detail_for_id",
    "persona_session_db_scope",
]


# STAGE 6 (duplicate-implementation retirement, 2026-08-22). Three names stood
# here and went together, because they were one lane:
#
# * ``write_snapshot(snapshot)`` — the ``snapshot.json`` boot-cache writer, which
#   also carried a ``read_model_enabled()``-gated ``ReadModel().apply_full_rebuild``
#   call. It had exactly ONE production caller in the repo,
#   ``read_model.resolve_snapshot_frame``, reached only from the ``harness
#   snapshot`` CLI verb; the serve path bypassed it by design and said so.
# * ``_sweep_stale_snapshot_tmp_files`` — swept ``.snapshot_*.tmp`` staging files
#   left by ``atomic_json_write``. It ran ONLY at a boot-cache write, so with the
#   writer gone it has neither a caller nor anything to sweep: nothing stages a
#   ``.snapshot_*.tmp`` in the store root any more.
# * ``_STALE_SNAPSHOT_TMP_AGE_SECONDS`` — that sweep's age gate.
#
# What made this a delete rather than a rewire: the CONSUMER had already left.
# The launcher's cold-paint lane read ``snapshot.json`` until MC-7 / P11 retired
# it (``mission_control_snapshot.dart:187`` records the retirement; a grep of the
# launcher's ``lib/`` finds no reader), so the boot cache served no boot. The
# live serve lane persists its cores somewhere else entirely — under
# ``<store_root>/serve_read_model/`` through ``core_cache.write_back()`` — with a
# stat fingerprint for validity rather than a stored watermark.
#
# ``paths.snapshot_path()`` SURVIVES this cut deliberately: it is the one
# authority for where that file would live, it is what an operator or a migration
# needs in order to find and remove a stale copy left by an older build, and it
# is pinned by ``tests/agent_runtime/test_paths.py``.


def _default_persona_session_db():
    # Same acquisition as the projection lane it feeds — see
    # ``chat_session_scope`` for the resolution ladder.
    from ..chat_session_scope import open_chat_session_db

    return open_chat_session_db()


@contextmanager
def persona_session_db_scope():
    """Acquire the projection's chat ``SessionDB`` and CLOSE it on the way out.

    MCF-27: every led build used to bind ``_default_persona_session_db()`` into a
    local and drop it, so a serve accumulated one live SQLite connection per
    build for its whole life. That was not merely untidy — it is why the chat
    ``-wal`` was present mid-session at all, and therefore why "which build in
    this process wrote the sidecar last" decided whether the NEXT boot's core
    cache could hit (MCF-15). Two call sites shared the acquisition
    (``_build_snapshot_uncoalesced`` and ``status.build_status``), so ownership
    became a scope rather than a close bolted onto each of them.

    ``open_chat_session_db`` answers **None by contract** when the database is
    unavailable, and every consumer of this handle types it ``Any | None``. So the
    None arm is explicit here: ``contextlib.closing`` over a bare ``None`` raises
    ``TypeError`` at exit and would turn an unavailable chat store — an ordinary,
    already-handled state — into a failed build.

    **Why closing here cannot poison the key the build is about to be stored
    under.** ``build_snapshot`` stats the input fingerprint BEFORE it calls the
    builder (``core_cache.write_back``'s docstring owns that direction argument),
    so the key is already captured when this scope exits. And the close is
    key-NEUTRAL only because MC-3b's ``core_cache._wal_without_frames_is_content_free``
    landed: ``SessionDB.close`` drains the token queue and attempts a TRUNCATE
    checkpoint, and SQLite unlinks the WAL when the last connection goes — so an
    absent WAL and a frameless present one must key identically, which is exactly
    what that collapse guarantees. Reverting it would make this close mint a miss.
    """

    session_db = _default_persona_session_db()
    try:
        yield session_db
    finally:
        if session_db is not None:
            try:
                session_db.close()
            except Exception:  # noqa: BLE001 — a build must not fail on release
                logger.debug("closing the projection chat SessionDB failed", exc_info=True)


def _agent_tool_detail(agent) -> dict:
    """The evicted tool-detail payloads for one persona (``agents`` section row),
    rebuilt read-only — the same fields ``_agent_summary`` carried before R2 evicted
    them (minus the retired ``agent_hud_state``)."""

    from ..tool_visibility import permission_state_for_persona, turn_tool_context_for_persona

    tool_resolution = resolve_tool_visibility(agent)
    return {
        "persona_id": agent.id,
        "display_name": agent.display_name,
        "tool_resolution": tool_resolution,
        "turn_tool_context": turn_tool_context_for_persona(
            agent, visibility=tool_resolution
        ),
        "permission_state": permission_state_for_persona(
            agent, visibility=tool_resolution
        ),
        "blocked_tools": tool_resolution["blocked_tools"],
    }


def persona_instance_detail_for_id(entity_id: str, *, event_log=None) -> dict | None:
    """The tool-detail payloads R2 evicted from ``persona_instances`` / ``agents``
    rows, rebuilt read-only and served on demand by ``harness persona-instance
    detail``.

    Resolves ``entity_id`` as a live persona-instance id first (the same derived
    set the frame keys), then falls back to a persona (agent) id — both wire rows
    carry a ``visibility_ref`` pointing here. Read-only (lists stores, mutates
    nothing). Returns ``None`` on a genuine miss (an honest ``not_found`` the
    launcher surfaces as 'unavailable', never a fabricated empty payload)."""

    token = str(entity_id or "").strip()
    if not token:
        return None
    from ..config import ensure_persisted_personas
    from ..persona_assignments import persona_instance_tool_detail

    event_log = event_log or CachedEventLog()
    agents = AgentStore().list_all()
    personas_by_id = {str(getattr(a, "id", "") or ""): a for a in agents}
    for instance in PersonaInstanceStore(event_log=event_log).ensure_for_personas(agents):
        if str(getattr(instance, "id", "") or "") == token:
            persona = personas_by_id.get(str(getattr(instance, "persona_id", "") or ""))
            return persona_instance_tool_detail(instance, persona, roster=ensure_persisted_personas)
    persona = personas_by_id.get(token)
    if persona is not None:
        return _agent_tool_detail(persona)
    return None
