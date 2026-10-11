"""``hermes harness workspace slots``: the argv mirror of the repo-slot RPC doors (build plan §3.4).

Every verb calls the store function the ``runtime.workspace.slots.*`` / ``.slot.*`` method
calls; this module holds no rule of its own. ``bind`` writes ``roots.<slot>`` through
``write_machine_roots`` exactly as ``harness roots set`` does.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from hermes_cli.flag_binding import list_flag_or_empty
from hermes_cli.harness_parts.verb_runner import run_refusing_verb

__layer__ = "lanes"
__all__ = [
    "_cmd_workspace_slots_bind",
    "_cmd_workspace_slots_clone",
    "_cmd_workspace_slots_declare",
    "_cmd_workspace_slots_env_set",
    "_cmd_workspace_slots_report",
    "_cmd_workspace_slots_show",
]


def _issued_at(args) -> str:
    return str(getattr(args, "issued_at", None) or datetime.now(timezone.utc).isoformat())


def _pairs(values, name: str) -> dict[str, str]:
    out = {}
    for item in values or []:
        key, sep, value = str(item).partition("=")
        if not sep or not key.strip():
            raise ValueError(f"{name} expects KEY=VALUE, got {item!r}")
        out[key.strip()] = value
    return out


def _run_workspace_slot_verb(args, kind: str, action) -> int:
    from agent_runtime.workspace_slot_env import SlotEnvRefused
    from agent_runtime.workspace_slots import SlotRefused

    return run_refusing_verb(args, kind, action, refusals=(SlotRefused, SlotEnvRefused), plain=(ValueError,))


def _cmd_workspace_slots_show(args) -> int:
    from agent_runtime.workspace_slots import show

    return _run_workspace_slot_verb(args, "workspace_slots", lambda: show(str(args.workspace_id)))


def _cmd_workspace_slots_declare(args) -> int:
    from agent_runtime.workspace_slots import declare, machine_id, require_publish_right

    def action():
        slots = json.loads(Path(str(args.slots_file)).read_text(encoding="utf-8"))
        require_publish_right(str(args.workspace_id))
        return declare(str(args.workspace_id), slots, issued_at=_issued_at(args), machine=machine_id())

    return _run_workspace_slot_verb(args, "workspace_slots_declare", action)


def _cmd_workspace_slots_bind(args) -> int:
    from agent_runtime.workspace_slots import bind

    return _run_workspace_slot_verb(args, "workspace_slot_bind",
                lambda: bind(str(args.workspace_id), str(args.slot), str(args.path), issued_at=_issued_at(args)))


def _cmd_workspace_slots_env_set(args) -> int:
    from agent_runtime.workspace_slot_env import set_slot_fill
    from agent_runtime.workspace_slots import REASON_SLOT_NOT_DECLARED, SlotRefused, live_slots, load_document, secret_keys
    from agent_runtime.workspace_slots_probe import report

    def action():
        workspace_id, slot = str(args.workspace_id), str(args.slot)
        declared = live_slots(load_document(workspace_id)).get(slot)
        if declared is None:
            raise SlotRefused(REASON_SLOT_NOT_DECLARED, slot)
        # A fill is written whole (replace): an absent --path-prepend / --env-keep means "none".
        fill = set_slot_fill(workspace_id, slot, env=_pairs(args.env, "--env"),
                             tool_paths=_pairs(args.tool_path, "--tool-path"), path_prepend=list_flag_or_empty(args, "path_prepend"),
                             dotenv=args.dotenv, venv=args.venv, secret_keys=secret_keys(declared),
                             issued_at=_issued_at(args), env_keep=list_flag_or_empty(args, "env_keep"))
        return {"slot": slot, "env_keys": sorted(fill.env), "report": report(workspace_id)["slots"].get(slot, {}),
                "env_keep_missing": sorted(set(list_flag_or_empty(args, "env_keep")) - set(fill.env))}

    return _run_workspace_slot_verb(args, "workspace_slot_env", action)


def _cmd_workspace_slots_report(args) -> int:
    from agent_runtime.workspace_slots_probe import report

    return _run_workspace_slot_verb(args, "workspace_slots_report", lambda: report(str(args.workspace_id)))


def _cmd_workspace_slots_clone(args) -> int:
    """The same spawn ``runtime.workspace.slot.clone`` makes; the CLI then WAITS for the run to
    settle (bind on success, the typed ending otherwise), because no serve outlives it to do so."""

    from agent_runtime.workspace_slot_setup import clone_slot, spawning_registry, watch_run

    def action():
        registry = spawning_registry()
        started = clone_slot(str(args.workspace_id), str(args.slot), str(args.dest_path), issued_at=_issued_at(args),
                             registry=registry, watch=False)
        return {**started, "run": watch_run(started["run"]["run_id"], registry) or started["run"]}

    return _run_workspace_slot_verb(args, "workspace_slot_clone", action)
