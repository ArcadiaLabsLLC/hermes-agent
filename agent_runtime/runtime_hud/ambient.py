"""The chat-side wrappers that do the I/O, then call the pure resolvers.

``situational_hud_for_instance`` (the stores, the scoped roster, the board
digest, the paired installs) and ``capability_block_for_persona`` (the
permission posture, the chat-lane drops, the envelope view). Best-effort: each
returns ``{}`` on failure — a HUD decorates a turn, it never blocks one. The
lazy ``persona_runtime`` reach lives here and nowhere else in the package.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.runtime_hud.capability import resolve_capability_block
from agent_runtime.runtime_hud.hud import resolve_situational_hud

__layer__ = "lanes"


def installs_block() -> list[dict[str, Any]]:
    """The paired-install rows for the HUD. Best effort, and it DIALS NOTHING.

    Wrapped here rather than at each feeder so both — the chat turn and the
    observability snapshot — resolve it through one call, and so the "``[]`` on
    any failure" guarantee is stated once. The peer store lives at the HEAD
    home's root and never the ambient one (``gateway_targets.peer_store_root``'s
    argument): ``HERMES_HOME`` is flipped process-globally for the length of
    every persona turn, which is exactly when this runs.
    """

    try:
        from ..gateway_targets import peer_store_root
        from ..peer_directory import installs_hud_block

        return installs_hud_block(peer_store_root())
    except Exception:
        return []


def capability_block_for_persona(
    persona: Any,
    *,
    session_id: str | None = None,
    permission_mode: str | None = None,
    lane: str | None = None,
) -> dict[str, Any]:
    """Chat-side convenience: resolve both capability accounts for one persona.

    The wrapper twin of :func:`situational_hud_for_instance` — it does the
    lookups a single mission-chat turn needs, then calls the same pure
    :func:`resolve_capability_block` (one authority). Both halves resolve the
    SAME functions the turn itself resolves (``chat_lane_capability_drops`` is
    the accounting twin of ``_enabled_toolsets_for_chat``;
    ``explain_terminal_envelope`` reads the same grants
    ``envelope_decision`` will), so what the agent is told and what the runtime
    then does cannot disagree.

    The two halves degrade INDEPENDENTLY: a fault resolving the drops must not
    blank the envelope posture, and vice versa. Best-effort overall — the
    capability account decorates a turn, it never blocks one.
    """

    if persona is None:
        return {}

    # The posture this turn runs under. Resolved through the ONE chokepoint (a
    # caller-supplied ``permission_mode`` still wins, for the hypothetical
    # ``persona tool-diff --permission-mode`` preview) and threaded into BOTH
    # halves: the envelope view is mode-aware since 2026-08-09, so reading it
    # without the mode would tell the agent classes are refused that its very
    # next command would run.
    mode = str(permission_mode or "").strip()
    source = ""
    if not mode:
        try:
            from ..tool_permissions import permission_options_for_chat

            resolved = permission_options_for_chat(persona, session_id=session_id)
            mode = str(resolved.permission_mode or "")
            source = str(resolved.permission_source or "")
        except Exception:
            mode = ""

    drops: tuple[Any, ...] = ()
    try:
        # Deferred: ``persona_runtime`` pulls the runtime graph (and imports this
        # module's siblings), so a module-level import here would be circular.
        from ..persona_runtime import chat_lane_capability_drops

        drops = chat_lane_capability_drops(
            persona, session_id=session_id, permission_mode=permission_mode
        )
    except Exception:
        drops = ()

    envelope: dict[str, Any] | None = None
    try:
        from ..personas import role_or_attr
        from ..terminal_envelope.classes import LANE_MISSION_CHAT
        from ..terminal_envelope.decision import explain_terminal_envelope

        envelope = explain_terminal_envelope(
            role=role_or_attr(persona),
            lane=str(lane or "").strip() or LANE_MISSION_CHAT,
            permission_mode=mode,
        )
    except Exception:
        envelope = None

    return resolve_capability_block(
        drops=drops,
        envelope=envelope,
        permission_mode=mode,
        permission_source=source,
    )


def _board_digest_for_workspace(workspace_id: str | None) -> dict[str, Any] | None:
    """Count open (non-done) cards on the active workspace's default board, by
    typed column kind. Returns ``None`` when there is no board or no open cards,
    so a workspace with no board contributes no HUD line. One store read per chat
    turn (chat-side wrapper only — never on the snapshot's per-lane hot path)."""

    if not workspace_id:
        return None
    try:
        from .. import board_models
        from ..board_store import BoardStore

        store = BoardStore()
        board_id = board_models.default_board_id(workspace_id)
        if not store.exists(board_id):
            return None
        board = store.get(board_id)
        kind_by_column = {column.column_id: column.kind for column in board.columns}
        counts: dict[str, int] = {}
        for card in store.list_cards(board_id):
            kind = kind_by_column.get(card.column_id, "custom")
            counts[kind] = counts.get(kind, 0) + 1
        digest = {key: counts.get(key, 0) for key in ("queued", "active", "review")}
        return digest if any(digest.values()) else None
    except Exception:
        return None


def situational_hud_for_instance(
    instance: Any,
    *,
    turn_budget: dict[str, Any] | None = None,
    capability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chat-side convenience: load the ambient runtime facts for one lane and
    resolve the situational HUD dict.

    The snapshot path resolves the same projection from data it already has
    loaded; this wrapper does the store I/O for a single mission-chat turn, then
    calls the same pure `resolve_situational_hud` (one authority). The chat
    caller renders THIS dict into the fed block AND records it verbatim on the
    turn's observability row, so the Mission Control CONTEXT peek shows exactly
    the object that was injected — parity by construction, not by later
    re-derivation. Best-effort: returns {} on any failure so a chat turn is
    never blocked by situational-HUD assembly."""

    if instance is None:
        return {}
    try:
        # Deferred imports keep module load order robust (context_builder, the
        # stores, and daemon all pull sizeable graphs).
        from .. import workspace_scope
        from ..persona_assignments import PersonaInstanceStore, is_canonical_persona_channel
        from ..store import RealmStore, WorkspaceStore

        # The FULL roster stays available for identity (steering) resolution; the
        # ADDRESSABLE roster fed to advertising/thread-count is scoped to this
        # lane's own workspace, has runtime-global canonical plumbing rows
        # excluded (instance = in-level placement — the "On level" block lists
        # ONLY what is actually placed on this level), and has each persona's
        # surviving canonical row shadowed behind any in-scope placement. So a
        # placement in another workspace is never offered here, and an unplaced
        # persona no longer advertises its canonical row onto every level.
        identity_roster = PersonaInstanceStore().list_all()

        workspace_store = WorkspaceStore()
        realm_store = RealmStore()
        scope_workspace_id = workspace_scope.effective_workspace_id(
            instance, active_workspace_id=workspace_store.active_id()
        )
        scoped_roster = workspace_scope.addressable_roster(
            identity_roster,
            scope_workspace_id=scope_workspace_id,
            is_canonical=is_canonical_persona_channel,
        )
        # The scope line names the lane's OWN workspace when it carries a pointer
        # (fallback: the active workspace), so it matches the scoped roster.
        workspace = next(
            (
                getattr(item, "name", None)
                for item in workspace_store.list_all(include_archived=True)
                if getattr(item, "id", None) == scope_workspace_id
            ),
            None,
        )
        realm = next(
            (
                getattr(item, "name", None)
                for item in realm_store.list_all(include_archived=True)
                if getattr(item, "id", None) == realm_store.active_id()
            ),
            None,
        )

        return resolve_situational_hud(
            instance,
            daemon=None,
            realm=realm,
            workspace=workspace,
            roster=scoped_roster,
            identity_roster=identity_roster,
            board=_board_digest_for_workspace(scope_workspace_id),
            turn_budget=turn_budget,
            capability=capability,
            installs=installs_block(),
        )
    except Exception:
        return {}
