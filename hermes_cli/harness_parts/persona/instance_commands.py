"""Persona-instance verbs: close, archive, retire, repair-steering, steer, return-summary, update-profile.

Separate because they act on one placed instance and its steering edges.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Final, Mapping
from agent_runtime.cli_format import emit_json
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.continuity import return_summary_to_parent_session
from agent_runtime.coordinator_permissions import review_coordinator_budget
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    persona_instance_summary,
    safe_assignment_text,
    safe_assignment_token,
    safe_optional_token,
)
from hermes_cli.flag_binding import list_flag_or_absent, list_flag_or_empty
from .chat_coordinator import (
    _coordinator_actor_id,
    _coordinator_confirm_payload,
    _coordinator_scope_from_args,
)
from .chat_target import _close_free_floating_assignments, _persona_by_id
from .lifecycle_commands import _agent_retire_outcome

__layer__ = "lanes"
__all__ = [
    "_cmd_persona_instance_archive",
    "_cmd_persona_instance_close",
    "_cmd_persona_instance_repair_steering",
    "_cmd_persona_instance_retire",
    "_cmd_persona_instance_return_summary",
    "_cmd_persona_instance_steer",
    "_cmd_persona_instance_update_profile",
]


def _cmd_persona_instance_close(args) -> int:
    cfg = load_agent_runtime_config()
    coordinator_id = _coordinator_actor_id(args)
    if coordinator_id:
        try:
            target = PersonaInstanceStore().get(args.persona_instance_id)
            persona = _persona_by_id(cfg, target.persona_id)
        except Exception:
            target = None
            persona = None
        scope = _coordinator_scope_from_args(args, cfg, persona)
        auth = review_coordinator_budget(
            "persona.instance.close",
            scope,
            target,
            actor=coordinator_id,
            coordinator_id=coordinator_id,
        )
        if not auth.ok:
            data = _coordinator_confirm_payload("persona.instance.close", coordinator_id, auth)
            print(emit_json(data) if args.json else data["status"])
            return 2
    return _close_free_floating_assignments(args.persona_instance_id, reason=args.reason, json_output=args.json, terminal_state="cancelled")


def _cmd_persona_instance_archive(args) -> int:
    return _close_free_floating_assignments(args.persona_instance_id, reason=args.reason, json_output=args.json, terminal_state="completed")


def _cmd_persona_instance_retire(args) -> int:
    """Instance end-of-life: archive a placement-backed persona-instance ROW.

    Unlike ``close``/``archive`` (which act on free-floating ASSIGNMENTS), this
    verb ends the deliberate instance itself — the operator ruling that deleting
    a placement is the instance's end-of-life. Refusals surface the typed
    ``PersonaInstanceRetireError.code`` so the launcher/operator can distinguish
    canonical-channel / active-binding / active-assignment / not-found."""
    cfg = load_agent_runtime_config()
    store = PersonaInstanceStore()
    coordinator_id = _coordinator_actor_id(args)
    if coordinator_id:
        try:
            target = store.get(args.persona_instance_id)
            persona = _persona_by_id(cfg, target.persona_id)
        except Exception:
            target = None
            persona = None
        scope = _coordinator_scope_from_args(args, cfg, persona)
        auth = review_coordinator_budget(
            "persona.instance.retire",
            scope,
            target,
            actor=coordinator_id,
            coordinator_id=coordinator_id,
        )
        if not auth.ok:
            data = _coordinator_confirm_payload("persona.instance.retire", coordinator_id, auth)
            print(emit_json(data) if args.json else data["status"])
            return 2
    # DELEGATES to the shared service (plan S5/D7) rather than calling the store
    # itself: the ack this verb prints and the one `harness agent retire` and
    # `runtime.agent.retire` print are now the same object built by the same
    # function, so ``archived_actor_keys`` / ``office_archive_failures`` /
    # ``already_retired`` arrive here too and a scripted operator does not have
    # to know which door they typed. The ENVELOPE below is unchanged — this
    # verb's `persona_instance_retired` key and its `code`-spelled refusal are
    # its operator surface, and the refusal is rendered from the service's typed
    # data rather than from a second `except` over the same store guard.
    outcome = _agent_retire_outcome(args)
    if outcome.refusal is not None:
        refusal = outcome.refusal
        reason = refusal.data.get("reason")
        data = {
            "ok": False,
            "error": reason,
            "code": reason,
            "message": refusal.message,
            **{k: v for k, v in refusal.data.items() if k != "reason"},
        }
        print(emit_json(data) if args.json else f"{reason}: {refusal.message}")
        return 2
    result = outcome.result
    data = {"ok": True, "persona_instance_retired": result}
    if args.json:
        print(emit_json(data))
    else:
        print(
            f"retired {result['persona_instance_id']} "
            f"({result['display_name']}) -> {result['archive_path']}"
        )
    return 0


# S66 removed ``_cmd_persona_instance_sweep_orphans`` and its ``sweep-orphans``
# subparser. The janitor it invoked reaped instances whose OWNING TASK had gone
# terminal, and S65 (`f9aa0faab`) retired that entire basis in ONE commit: the
# store method, the owner-release inference behind it, and the goal/task path
# helpers it read (`paths.task_path` / `goal_path` / `goals_dir`). Only the
# caller survived, so the verb raised `AttributeError` on every invocation. It
# is not restorable without a contract move either — the reap emitted
# `persona_instance.reaped`, which the same wave DE-REGISTERED, so
# `EventLog.append` would now refuse it. Retiring a placement is
# `persona instance retire`, which is live and untouched.


def _cmd_persona_instance_repair_steering(args) -> int:
    """Strip non-instance principals (e.g. the operator) out of a persona
    instance's steering fields. A steering parent is a persona-instance id; a
    principal that leaked into ``steered_by`` / ``spawned_by`` via a legacy mint
    renders as a phantom "steered by <principal>" edge. Honors --dry-run
    (validate + preview, write nothing, emit nothing)."""
    cfg = load_agent_runtime_config()
    target = safe_optional_token(getattr(args, "persona_instance_id", None))
    scan_all = bool(getattr(args, "all", False))
    if not target and not scan_all:
        data = {"ok": False, "error": "pass a persona_instance_id or --all"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    if target and scan_all:
        data = {"ok": False, "error": "pass either a persona_instance_id or --all, not both"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    dry_run = bool(getattr(args, "dry_run", False))
    store = PersonaInstanceStore()
    try:
        result = store.repair_non_instance_steering(target or None, apply=not dry_run)
    except Exception as exc:
        data = {"ok": False, "error": safe_assignment_text(str(exc), limit=240) or "repair failed"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    data = {"ok": True, "dry_run": dry_run, "persona_instance_steering_repair": result}
    if args.json:
        print(emit_json(data))
    else:
        verb = "would repair" if dry_run else "repaired"
        print(f"{verb} {result['repaired_count']} row(s) with non-instance steering entries")
        for rec in result["repaired"]:
            print(
                f"  {rec['persona_instance_id']}: "
                f"steered_by {rec['steered_by_before']} -> {rec['steered_by_after']}; "
                f"spawned_by {rec['spawned_by_before']!r} -> {rec['spawned_by_after']!r}; "
                f"removed {rec['removed_steered_by']}"
            )
    return 0


#: The steer vocabulary: each operation's name -> what it does to the store.
#: The ONE reader of an op name — the flag selection below is built from these
#: keys, in this order, so an op outside the table cannot be selected. ``parent``
#: is the back-compat alias for "replace the set with this single parent".
_STEER_OPS: Final[Mapping[str, Callable[[PersonaInstanceStore, str, Any, str | None], Any]]] = MappingProxyType(
    {
        "detach": lambda store, instance_id, _value, _goal_id: store.detach_parents(instance_id),
        "parent": lambda store, instance_id, value, goal_id: store.set_parents(instance_id, [value], goal_id=goal_id),
        "set_parents": lambda store, instance_id, value, goal_id: store.set_parents(
            instance_id, list(value or []), goal_id=goal_id
        ),
        "add_parent": lambda store, instance_id, value, goal_id: store.add_parent(instance_id, value, goal_id=goal_id),
        "remove_parent": lambda store, instance_id, value, _goal_id: store.remove_parent(instance_id, value),
    }
)


def _cmd_persona_instance_steer(args) -> int:
    cfg = load_agent_runtime_config()
    persona_instance_id = safe_assignment_token(args.persona_instance_id)
    if not persona_instance_id:
        data = {"ok": False, "error": "persona_instance_id is required"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    # Exactly one steering operation. --parent stays a back-compat alias for
    # "replace the set with this single parent"; the multi-parent verbs are
    # additive (--add-parent / --remove-parent) or declarative (--set-parents).
    detach = bool(getattr(args, "detach", False))
    parent_instance_id = safe_optional_token(getattr(args, "parent_instance_id", None))
    add_parent = safe_optional_token(getattr(args, "add_parent", None))
    remove_parent = safe_optional_token(getattr(args, "remove_parent", None))
    set_parents_raw = getattr(args, "set_parents", None)
    goal_id = None if detach else safe_optional_token(getattr(args, "goal_id", None))
    # op -> (present on the command line, the value its store call takes).
    requested = {
        "detach": (detach, None),
        "parent": (bool(parent_instance_id), parent_instance_id),
        "set_parents": (set_parents_raw is not None, set_parents_raw),
        "add_parent": (bool(add_parent), add_parent),
        "remove_parent": (bool(remove_parent), remove_parent),
    }
    selected = [name for name in _STEER_OPS if requested[name][0]]
    if not selected:
        data = {"ok": False, "error": "one of --parent / --add-parent / --remove-parent / --set-parents / --detach is required"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    if len(selected) > 1:
        data = {"ok": False, "error": f"steer operations are mutually exclusive: got {', '.join(selected)}"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    op = selected[0]
    store = PersonaInstanceStore()
    try:
        target = store.get(persona_instance_id)
    except Exception:
        data = {"ok": False, "error": f"persona instance not found: {persona_instance_id}"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    before = list(target.steered_by)
    # 76D.3: re-routing a steering edge is a STEER verb (ungated); operator
    # actors bypass entirely. Coordinators still pass through the authorizer so
    # the contract stays uniform with create/kill paths.
    coordinator_id = _coordinator_actor_id(args)
    if coordinator_id:
        persona = _persona_by_id(cfg, target.persona_id)
        scope = _coordinator_scope_from_args(args, cfg, persona)
        auth = review_coordinator_budget("re_route", scope, target, actor=coordinator_id, coordinator_id=coordinator_id)
        if not auth.ok:
            data = _coordinator_confirm_payload("re_route", coordinator_id, auth)
            print(emit_json(data) if args.json else data["status"])
            return 2
    try:
        updated = _STEER_OPS[op](store, persona_instance_id, requested[op][1], goal_id)
    except ValueError as exc:
        data = {"ok": False, "error": str(exc)}
        print(emit_json(data) if args.json else data["error"])
        return 2
    try:
        persona = _persona_by_id(cfg, updated.persona_id)
    except Exception:
        persona = None
    after = list(updated.steered_by)
    added = [pid for pid in after if pid not in before]
    removed = [pid for pid in before if pid not in after]
    data = {
        "ok": True,
        "detached": not after,
        "steered_by": after,
        "added": added,
        "removed": removed,
        "instance": persona_instance_summary(updated, persona),
    }
    parents_label = ",".join(after) if after else "(none)"
    print(emit_json(data) if args.json else f"steered {persona_instance_id}: parents={parents_label} goal={updated.goal_id}")
    return 0


def _cmd_persona_instance_return_summary(args) -> int:
    try:
        data = return_summary_to_parent_session(
            args.persona_instance_id,
            parent_session_id=args.parent_session_id,
            summary=args.summary,
            proof_ids=list_flag_or_empty(args, "proof_ids"),
            artifact_refs=list_flag_or_empty(args, "artifact_refs"),
        )
    except Exception as exc:
        data = {"ok": False, "capability_id": "persona.instance.return_summary", "error": safe_assignment_text(str(exc), limit=240)}
        print(emit_json(data) if args.json else data["error"])
        return 2
    print(emit_json(data) if args.json else f"returned {data['persona_instance_id']} -> {data['parent_session_id']}")
    return 0


def _cmd_persona_instance_update_profile(args) -> int:
    cfg = load_agent_runtime_config()
    persona_instance_id = safe_assignment_token(args.persona_instance_id)
    if not persona_instance_id:
        data = {"ok": False, "error": "persona_instance_id is required"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    store = PersonaInstanceStore()
    try:
        target = store.get(persona_instance_id)
    except Exception:
        data = {"ok": False, "error": f"persona instance not found: {persona_instance_id}"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    coordinator_id = _coordinator_actor_id(args)
    if coordinator_id:
        persona = _persona_by_id(cfg, target.persona_id)
        scope = _coordinator_scope_from_args(args, cfg, persona)
        auth = review_coordinator_budget("persona.instance.update_profile", scope, target, actor=coordinator_id, coordinator_id=coordinator_id)
        if not auth.ok:
            data = _coordinator_confirm_payload("persona.instance.update_profile", coordinator_id, auth)
            print(emit_json(data) if args.json else data["status"])
            return 2
    requested_skills = list_flag_or_absent(args, "skills")
    try:
        updated = store.update_profile(
            persona_instance_id,
            display_name=getattr(args, "display_name", None),
            current_chat_goal=getattr(args, "current_chat_goal", None),
            goal_id=getattr(args, "goal_id", None),
            # `None` when the flag was not given, and NEVER `[]` — which is
            # the whole content of `list_flag_or_absent`. Three handlers in
            # this file had each re-derived that rule in its own paragraph
            # before the reader existed; the name now carries it.
            #
            # THE BUG THIS REPLACES. `list(... or [])` handed the store an empty
            # LIST for every call that omitted `--skill`, and the store's own
            # contract is `if skills is not None or clear_skills:` — correct, and
            # correctly read as "the caller sent a list, write it". So
            # `persona instance update-profile <id> --display-name X` CLEARED
            # every skill override on that instance, silently, and the operator
            # who renamed an agent lost the skills it was assigned. The store was
            # never wrong; the collapse happened here, in the layer that is
            # supposed to translate "absent" into "absent".
            #
            # The launcher already defends against it from the outside
            # (`agent_chat/skills_context_controller.dart` refuses to write an
            # unproven baseline), which is a client working around a server bug —
            # not a fix, and not something a cron script or a remote `call` gets.
            skills=requested_skills,
            clear_skills=bool(getattr(args, "clear_skills", False)),
            # The third value of the skills tri-state, and the only one that
            # had no door before 2026-09-03: `--clear-skills` writes `[]`
            # ("explicitly none"), never `null` ("follow the template again"),
            # so one Save at "this agent" scope pinned the agent off its
            # persona forever. `getattr` with a default, like its siblings,
            # because `harness call` builds an args namespace by hand.
            inherit_skills=bool(getattr(args, "inherit_skills", False)),
        )
    except ValueError as exc:
        data = {"ok": False, "error": str(exc)}
        print(emit_json(data) if args.json else data["error"])
        return 2
    try:
        persona = _persona_by_id(cfg, updated.persona_id)
    except Exception:
        persona = None
    data = {
        "ok": True,
        "persona_instance_id": updated.id,
        "persona_id": updated.persona_id,
        "backing_profile": updated.profile_id,
        "updated_instance": persona_instance_summary(updated, persona),
        "next_expected": "refresh Harness snapshot; runtime instance overrides should be visible without modifying the backing Hermes profile",
    }
    print(emit_json(data) if args.json else f"updated runtime profile {updated.id}")
    return 0
