"""``hermes harness persona slots``: the argv mirror of ``runtime.persona.instance.slots.*`` (build plan §3.4).

Both verbs call ``agent_runtime.persona_slots`` — the same functions the RPC methods call;
this module holds no rule of its own.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hermes_cli.harness_support import _object_envelope, _print_stage42, emit_harness_error

__layer__ = "lanes"
__all__ = ["_cmd_persona_slots_set", "_cmd_persona_slots_show"]


def _run(args, kind: str, action) -> int:
    from agent_runtime.persona_slots import SlotAssignmentRefused

    try:
        payload = action()
    except SlotAssignmentRefused as exc:
        return emit_harness_error(exc, args=args, code="invalid_payload", message=f"{exc.reason}: {exc.detail}")
    _print_stage42(_object_envelope(kind, payload), args=args, default_output="json")
    return 0


def _cmd_persona_slots_show(args) -> int:
    from agent_runtime.persona_slots import show_instance_slots

    return _run(args, "persona_instance_slots", lambda: show_instance_slots(str(args.persona_instance_id)))


def _cmd_persona_slots_set(args) -> int:
    from agent_runtime.persona_slots import set_instance_slots

    issued_at = str(getattr(args, "issued_at", None) or datetime.now(timezone.utc).isoformat())
    return _run(args, "persona_instance_slots", lambda: set_instance_slots(
        str(args.persona_instance_id), list(args.slot or []), getattr(args, "primary", None), issued_at=issued_at))
