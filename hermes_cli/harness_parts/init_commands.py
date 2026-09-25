"""``hermes harness init`` and ``install-harness-skills``: the store and skill bootstrap verbs.

Separate from ``runtime_commands`` so that module stays under the ceiling; both
verbs write the harness store or the skill roots once, at setup.
"""

from __future__ import annotations

from dataclasses import asdict

from agent_runtime.cli_format import emit_json
from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
from agent_runtime.default_scope import ensure_default_scope
from agent_runtime.errors import DefaultScopeReconciliationRequired
from agent_runtime.skill_install import install_harness_skills, install_harness_skills_for_personas
from hermes_cli.harness_support import emit_harness_error

__layer__ = "lanes"
__all__ = [
    "_cmd_init",
    "_cmd_install_harness_skills",
]


def _cmd_init(args) -> int:
    cfg = load_agent_runtime_config()
    personas = ensure_persisted_personas(cfg)
    persona_ids = [p.id for p in personas]
    try:
        scope = ensure_default_scope(agent_ids=persona_ids)
    except DefaultScopeReconciliationRequired as exc:
        return emit_harness_error(exc, args=args, code=exc.code)
    data = {
        "personas": persona_ids,
        "default_realm_id": scope.realm.id,
        "default_workspace_id": scope.workspace.id,
    }
    if args.json:
        print(emit_json(data))
    else:
        # Personas are data now: a fresh root provisions none, so the old
        # unconditional line rendered a dangling "personas: " with nothing after it.
        print(
            f"Initialized harness personas: {', '.join(data['personas'])}"
            if data["personas"]
            else "Initialized harness: no personas provisioned (personas are data — add them with `harness persona`)"
        )
        print(f"Default scope: {scope.realm.name} / {scope.workspace.name}")
    return 0


def _cmd_install_harness_skills(args) -> int:
    if getattr(args, "active_profile_only", False):
        results = install_harness_skills()
    else:
        results = install_harness_skills_for_personas(ensure_persisted_personas(load_agent_runtime_config()))
    data = {"installed": [asdict(result) for result in results], "ok": all(result.ok for result in results)}
    if args.json:
        print(emit_json(data))
    else:
        for result in results:
            state = "updated" if result.changed else "ok"
            print(f"{result.skill}: {state}")
    return 0 if data["ok"] else 1
