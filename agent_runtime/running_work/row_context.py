"""Who asked for a piece of running work, the workspace it runs in, and its plan's steps.

RT-RUNNING-WORK-ROWS-SAY-WHO-ASKED-WHERE-AND-WHICH-STEPS (review w1118a.55 D12): the
additive keys Running now's open card reads, through ``work_row``'s ``extra=``. Each
key says only what a store holds; a fact no store holds is ``None``, never a guess:

* ``asked_by`` — ``{"kind": "operator"}``, ``{"kind": "agent", persona_id,
  persona_instance_id, name}`` or ``{"kind": "delivery"}``; ``None`` when unknown
  (a turn read from the journal outside the process running it).
* ``workspace_id`` / ``workspace_name`` — the lane's workspace (``lane_workspace``).
* ``cwd`` — the folder the turn runs in (its run request's ``workdir``); ``None`` when
  not known here.
* ``plan["items"]`` — the plan's steps with their state; ``seconds`` is ``None``
  because the todo store keeps no time per step (no duration is invented).

The keys ride the row, so a row hidden from a caller hides them too.
"""

from __future__ import annotations

from typing import Any

from .rows import bounded_operator_text

__layer__ = "lanes"

__all__ = [
    "ASKED_BY_AGENT",
    "ASKED_BY_DELIVERY",
    "ASKED_BY_OPERATOR",
    "RowContext",
    "plan_items",
]

ASKED_BY_OPERATOR = "operator"
ASKED_BY_AGENT = "agent"
ASKED_BY_DELIVERY = "delivery"


class RowContext:
    """One projection pass's memo: an instance's name and workspace are read at most once."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._workspaces: dict[str, tuple[str | None, str | None]] = {}
        self._store: Any = None

    def agent(self, persona_id: Any, instance_id: Any) -> dict[str, Any]:
        """``asked_by`` for an agent: its persona, its instance and the name the operator knows it by."""

        persona = bounded_operator_text(persona_id, limit=120) or None
        instance = bounded_operator_text(instance_id, limit=200) or None
        return {
            "kind": ASKED_BY_AGENT,
            "persona_id": persona,
            "persona_instance_id": instance,
            "name": self._name(instance) or None,
        }

    def asked_by_marker(self, marker: Any) -> dict[str, Any]:
        """``asked_by`` from the turn's native user-row marker (``relay_policy``): none is the operator."""

        from ..relay_policy import parse_harness_delivery_marker, parse_relay_sender_marker

        sender = parse_relay_sender_marker(marker)
        if sender is not None:
            return self.agent(sender.persona_id, sender.instance_id)
        if parse_harness_delivery_marker(marker) is not None:
            return {"kind": ASKED_BY_DELIVERY}
        # No marker is how an operator's (or the CLI's, on their behalf) send is stored.
        return {"kind": ASKED_BY_OPERATOR}

    def workspace(self, instance_id: Any) -> dict[str, Any]:
        """``{"workspace_id", "workspace_name"}`` of an instance's lane, ``None`` each when unknown."""

        handle = bounded_operator_text(instance_id, limit=200)
        if not handle:
            return {"workspace_id": None, "workspace_name": None}
        if handle not in self._workspaces:
            self._workspaces[handle] = self._read_workspace(handle)
        workspace_id, name = self._workspaces[handle]
        return {"workspace_id": workspace_id, "workspace_name": name}

    def _read_workspace(self, handle: str) -> tuple[str | None, str | None]:
        try:
            from ..persona_assignments import PersonaInstanceStore
            from ..runtime_hud.ambient import lane_workspace_for_instance

            instance = PersonaInstanceStore().get(handle)
            if self._store is None:
                from ..store import WorkspaceStore

                self._store = WorkspaceStore()
            lane = lane_workspace_for_instance(instance, workspace_store=self._store)
        except Exception:
            return None, None
        return lane.id, lane.name

    def _name(self, instance: str | None) -> str:
        if not instance:
            return ""
        if instance not in self._names:
            from ..persona_assignments import persona_instance_display_name

            self._names[instance] = persona_instance_display_name(instance)
        return self._names[instance]


def plan_items(items: Any) -> list[dict[str, Any]]:
    """The plan's steps, bounded like ``todo_state``: ``{id, content, status, parent?, seconds}``.

    ``seconds`` is ``None``: the todo store keeps no time per step, and the card shows
    none rather than an invented duration.
    """

    try:
        from ..profile_runner.tool_payloads import _todo_state_items

        steps = _todo_state_items(list(items or ()))
    except Exception:
        return []
    return [{**step, "seconds": None} for step in steps]
