"""``hermes harness project``: the agent's door onto a Project's repo slots (RT-PROJECT-SLOTS-AGENT-VERBS).

The console reaches a Project through the ``runtime.project.*`` RPC verbs; an agent has a terminal,
so this is the same set as argv. Every verb but ``list`` calls the body the RPC method registers
(``agent_runtime.serve_rpc.project.PROJECT_VERBS``) with the params it would have sent, so the two
doors cannot answer differently; ``slot clone`` and ``recipe run-step`` call the store function
with a registry and WAIT for the run, as ``workspace slots clone`` does, because no serve outlives
the CLI to settle it. ``list`` (no RPC twin) is ``project_store.list_projects``.

A write into a Project held by a server-bound realm needs the launcher-brokered credential, which
argv does not carry: it answers ``realm_publish_denied`` naming the realm, never a silent write.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_cli.flag_binding import list_flag_or_empty
from hermes_cli.harness_parts.verb_runner import run_refusing_verb
from hermes_cli.harness_parts.workspace_slots_commands import _pairs

__layer__ = "lanes"
__all__ = [
    "_cmd_project_declare",
    "_cmd_project_list",
    "_cmd_project_recipe_run_step",
    "_cmd_project_recipe_set",
    "_cmd_project_recipe_show",
    "_cmd_project_report",
    "_cmd_project_show",
    "_cmd_project_slot_bind",
    "_cmd_project_slot_clone",
    "_cmd_project_slot_env_set",
]


def _project_issued_at(args) -> str:
    return str(getattr(args, "issued_at", None) or datetime.now(UTC).isoformat())


def _project_json_file(path) -> Any:
    return json.loads(Path(str(path)).read_text(encoding="utf-8-sig"))


def _emit_project_verb(args, kind: str, action) -> int:
    from agent_runtime.root_observability import attach_root_observability
    from agent_runtime.workspace_slot_env import SlotEnvRefused
    from agent_runtime.workspace_slot_recipe import RecipeRefused
    from agent_runtime.workspace_slots import SlotRefused

    return run_refusing_verb(args, kind, action, refusals=(SlotRefused, SlotEnvRefused, RecipeRefused),
                             plain=(ValueError,), stamp=lambda envelope: attach_root_observability(envelope))


def _run_project_rpc_body(args, kind: str, method: str, params: dict[str, Any]) -> int:
    """Run the RPC body of ``method`` over ``params`` and print its ``kind`` envelope."""

    from agent_runtime.serve_rpc.project import PROJECT_VERBS

    return _emit_project_verb(args, kind, lambda: PROJECT_VERBS[method](params))


def _cmd_project_list(args) -> int:
    from agent_runtime.project_store import list_projects

    return _emit_project_verb(args, "project_list", lambda: {"projects": list_projects()})


def _cmd_project_show(args) -> int:
    return _run_project_rpc_body(args, "project", "runtime.project.show", {"project_id": args.project_id})


def _cmd_project_report(args) -> int:
    return _run_project_rpc_body(args, "project_report", "runtime.project.report", {"project_id": args.project_id})


def _cmd_project_declare(args) -> int:
    from agent_runtime.serve_rpc.project import PROJECT_VERBS

    def action():
        params = {"project_id": args.project_id, "slots": _project_json_file(args.slots_file), "issued_at": _project_issued_at(args)}
        if args.name is not None:
            params["name"] = args.name
        return PROJECT_VERBS["runtime.project.declare"](params)

    return _emit_project_verb(args, "project_declare", action)


def _cmd_project_slot_bind(args) -> int:
    return _run_project_rpc_body(args, "project_slot_bind", "runtime.project.slot.bind",
                 {"project_id": args.project_id, "slot": args.slot, "path": args.path, "issued_at": _project_issued_at(args)})


def _cmd_project_slot_env_set(args) -> int:
    from agent_runtime.serve_rpc.project import PROJECT_VERBS

    def action():
        # A fill is written whole (replace): an absent --path-prepend / --keep means "none".
        return PROJECT_VERBS["runtime.project.slot.env.set"]({
            "project_id": args.project_id, "slot": args.slot, "env": _pairs(args.env, "--env"),
            "tool_paths": _pairs(args.tool_path, "--tool-path"), "path_prepend": list_flag_or_empty(args, "path_prepend"),
            "dotenv": args.dotenv, "venv": args.venv, "env_keep": list_flag_or_empty(args, "env_keep"),
            "issued_at": _project_issued_at(args)})

    return _emit_project_verb(args, "project_slot_env", action)


def _cmd_project_slot_clone(args) -> int:
    from agent_runtime.project_store import valid_project_id
    from agent_runtime.workspace_slot_setup import clone_slot, spawning_registry, watch_run

    def action():
        registry = spawning_registry()
        started = clone_slot(None, str(args.slot), str(args.dest_path), issued_at=_project_issued_at(args),
                             registry=registry, watch=False, project_id=valid_project_id(args.project_id))
        return {**started, "run": watch_run(started["run"]["run_id"], registry) or started["run"]}

    return _emit_project_verb(args, "project_slot_clone", action)


def _cmd_project_recipe_show(args) -> int:
    return _run_project_rpc_body(args, "project_recipe", "runtime.project.recipe.show", {"project_id": args.project_id})


def _cmd_project_recipe_set(args) -> int:
    from agent_runtime.serve_rpc.project import PROJECT_VERBS

    def action():
        return PROJECT_VERBS["runtime.project.recipe.set"]({
            "project_id": args.project_id, "slot": args.slot, "steps": _project_json_file(args.steps_file),
            "revision": args.revision, "persona_instance_id": args.persona_instance_id,
            "issued_at": _project_issued_at(args)})

    return _emit_project_verb(args, "project_recipe_set", action)


def _cmd_project_recipe_run_step(args) -> int:
    from agent_runtime.project_store import valid_project_id
    from agent_runtime.workspace_slot_setup import run_step, spawning_registry, watch_run

    def action():
        registry = spawning_registry()
        started = run_step(None, str(args.slot), str(args.step_id), issued_at=_project_issued_at(args), registry=registry,
                           watch=False, project_id=valid_project_id(args.project_id))
        return {**started, "run": watch_run(started["run"]["run_id"], registry) or started["run"]}

    return _emit_project_verb(args, "project_recipe_run_step", action)
