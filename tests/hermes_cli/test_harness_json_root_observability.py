"""Root-observability gate: every ``--json`` harness verb states WHICH root
answered, or carries a written reason why not.

The defect class (2026-08-12 ambient chat-history incident): a wrong runtime
root returns a well-formed EMPTY answer — ``ok: true, count: 0`` —
indistinguishable from genuinely-empty data, so any diagnostic that resolves
its own root always confirms health. The only durable fix is structural: the
envelope itself must carry its frame of reference
(``agent_runtime/root_observability.py``), and a NEW ``--json`` verb that
ships without it must fail CI until consciously classified below.

Pattern per ``tests/agent_runtime/test_store_event_invariant.py``: AST scan +
justified ledger + anti-rot checks on the ledger itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import hermes_cli.harness as harness_module
from tests._downstream.call_graph import CallGraph, module_name

_HARNESS_PY = Path(harness_module.__file__)
_PARTS_DIR = _HARNESS_PY.parent / "harness_parts"
_REPO_ROOT = _HARNESS_PY.parent.parent

# The JSON root (D3.17): a handler EMITS when its body reaches one of these
# through the resolved call graph (tests/_downstream/call_graph.py), bounded to
# the two packages below. ``_print_stage42`` and ``emit_operation_result`` emit
# because their bodies reach ``emit_json``, not because a name list says so.
_EMIT_ROOTS = {
    ("agent_runtime.cli_format", "emit_json"),
    ("agent_runtime.cli_format", "emit_json_line"),
}
_GRAPH_PACKAGES = ("hermes_cli", "agent_runtime")
# The one attach chokepoint (agent_runtime/root_observability.py).
_ATTACH_CALL = "attach_root_observability"

# Runtime functions an argv handler DELEGATES to that attach the block
# themselves: name -> whether they stamp ``chat_scope``. They exist because a
# verb with a method twin keeps its one implementation in ``agent_runtime``
# (lane h-twins), and the attach belongs with the envelope, not with the door
# that prints it. A source walk cannot see INTO them, so each entry is held to
# a RUNTIME proof instead — ``test_every_attaching_delegate_attaches`` calls it
# and reads the keys off the result. Do not add a name without a row there.
ATTACHING_DELEGATES = {
    "persona_chat_history_page": True,
    "realm_sync_revert": False,
    # agent_runtime.realm_verbs: the realm verbs' one implementation, both doors.
    "realm_sync_status": False,
    "realm_sync_pull": False,
    "realm_sync_publish": False,
    "realm_sync_resolve": False,
    "realm_skills_show": False,
    "realm_skills_set": False,
    "realm_agents_show": False,
    "realm_agents_set": False,
    "realm_adopt": False,
}

# Chat lanes must also stamp ``chat_scope`` — ``source: "ambient_home"``
# beside an empty result is the tell the incident lacked entirely.
#
# ``_cmd_status`` is here for the other half of the same property: it is the
# ORIENTATION verb, and since 2026-08-13 the head home is a durable runtime
# declaration (``config_declared``) rather than a string only the Launcher's
# spawn environment carried. Status must therefore be able to say which rung
# named the head it would read from — otherwise the runtime declares its own
# identity and the verb an operator uses to check it still cannot show it.
#
# ``_cmd_persona_instance_chat_bindings`` judges chat bindings AGAINST a
# SessionDB, so a wrong head corrupts both of its answers: ``stale_count: 0``
# reads as a clean store, and a named stale row is a false accusation against a
# live instance (the 2026-07-25 incident cleared 10 healthy bindings exactly
# that way). The verb refuses to answer unless the head was named — the stamp
# is how the envelope SHOWS which one.
CHAT_SCOPE_REQUIRED = {
    "_cmd_persona_chat_history",
    "_cmd_persona_instance_chat_bindings",
    "_cmd_status",
}

_BACKLOG_REASON = (
    "predates the resolution block (2026-08-12 root-observability wave); "
    "route the envelope through attach_root_observability when this verb is "
    "next touched. Do NOT add new verbs to this list with this reason."
)

# Handlers allowed to emit JSON WITHOUT the standard resolution block, each
# with the reason the exemption is sound. Adding a name here is a reviewed
# decision, not a default.
LEDGER: dict[str, str] = {
    name: _BACKLOG_REASON
    for name in (
        # harness_parts/ verb families (lane H2 split harness.py)
        "_cmd_roots_list", "_cmd_roots_set", "_cmd_roots_unset", "_cmd_roots_migrate",
        "_cmd_persona_instance_detail",
        "_cmd_skills_catalog", "_cmd_skills_publishable", "_cmd_skills_inbox",
        "_cmd_skills_promote", "_cmd_skills_inventory",
        "_cmd_prompt_context_show",
        "_cmd_workspace_list", "_cmd_workspace_show", "_cmd_workspace_create",
        "_cmd_workspace_delete", "_cmd_workspace_use",
        "_cmd_workspace_add_agent", "_cmd_workspace_remove_agent",
        "_cmd_workspace_rename", "_cmd_workspace_archive",
        "_cmd_realm_list", "_cmd_realm_show", "_cmd_realm_create",
        "_cmd_realm_bind_server", "_cmd_realm_use", "_cmd_realm_default_scope",
        "_cmd_realm_sync_held",
        "_cmd_agent_set_profile",
        "_cmd_pets_gallery", "_cmd_pets_install", "_cmd_pets_sprite", "_cmd_pets_thumb",
        "_cmd_init", "_cmd_install_harness_skills", "_cmd_providers",
        # harness_parts/board.py
        "_cmd_board_list", "_cmd_board_show", "_cmd_board_create", "_cmd_board_update",
        "_cmd_board_card_add", "_cmd_board_card_edit", "_cmd_board_card_move",
        "_cmd_board_card_archive", "_cmd_board_card_restore",
        "_cmd_board_resolve_conflict",
        # harness_parts/checkpoint_commands.py
        "_cmd_checkpoint_fetch", "_cmd_checkpoint_classes",
        # harness_parts/flow_commands.py
        "_cmd_flow_set", "_cmd_flow_show", "_cmd_flow_list",
        # harness_parts/office.py
        "_cmd_office_show", "_cmd_office_actor_upsert", "_cmd_office_actor_remove",
        "_cmd_office_actor_restore", "_cmd_office_set_folders",
        "_cmd_office_resolve_conflict",
        # harness_parts/persona/ (lane H3 split persona_commands.py)
        "_cmd_persona_list", "_cmd_persona_show", "_cmd_persona_tool_diff",
        "_cmd_persona_permission_set", "_cmd_persona_assignments",
        "_cmd_persona_assignment_task_id_migration",
        "_cmd_persona_instance_create", "_cmd_persona_instance_open_chat",
        "_cmd_persona_instance_open_new_chat", "_cmd_persona_chat_delete",
        "_cmd_mission_chat_steer", "_cmd_mission_chat_queue_skill",
        "_cmd_mission_chat_clarify_tickets", "_cmd_mission_chat_turn_resolve",
        "_cmd_persona_instance_close", "_cmd_persona_instance_retire",
        "_cmd_persona_instance_repair_steering", "_cmd_persona_instance_steer",
        "_cmd_persona_instance_return_summary", "_cmd_persona_instance_update_profile",
        "_cmd_persona_instance_set_model", "_cmd_persona_set_model",
        # harness_parts/runtime_commands.py
        "_cmd_worktree_reap", "_cmd_persona_instance_reconcile",
        "_cmd_health", "_cmd_config", "_cmd_migrate", "_cmd_observe",
        # ``_cmd_rebuild_read_model`` / ``_cmd_read_projection`` stood here until
        # Stage 6 (2026-08-22) retired the read_model.db lane with both verbs.
        "_cmd_contracts_dump",
        # harness_parts/work_commands.py (split from runtime_commands, h10b-refac)
        "_cmd_work_list", "_cmd_work_peek", "_cmd_work_cancel",
    )
}

# The handlers the import-graph scan (D3.17, 2026-10-10) found emitting that the
# hand-kept name set never saw, each family read and classified. None attaches
# today; each reason says why the exemption is sound or which row owns the fix.
_CHARSHEET_REASON = (
    "charsheet verb (emits through _characters_emit / _characters_auto_write): the "
    "payload key set is the charsheet contract pinned by "
    "tests/fixtures/charsheet_payload_contract.json and mirrored by the launcher, so "
    "a resolution key is a contract change owed with the launcher; until it lands an "
    "empty library is indistinguishable from a wrong root - runtime-queue row "
    "'charsheet and workspace-slot JSON verbs state no root' (D3.17)"
)
_WORKSPACE_SLOTS_REASON = (
    "repo-slot verb (emits through _run_workspace_slot_verb -> _print_stage42): the "
    "envelope names the workspace_id it read, but a slot document read from a wrong "
    "root is an empty document, not a refusal - runtime-queue row 'charsheet and "
    "workspace-slot JSON verbs state no root' (D3.17)"
)
_PERSONA_SLOTS_REASON = (
    "persona slot verb (emits through _run_slot_verb -> _print_stage42): the instance "
    "is read first (persona_slots._slot_instance), so a wrong root refuses the id "
    "rather than answering an empty slot list"
)
LEDGER.update({name: _CHARSHEET_REASON for name in (
    "_cmd_characters_add_state", "_cmd_characters_approve_direction", "_cmd_characters_auto",
    "_cmd_characters_backfill_home", "_cmd_characters_base", "_cmd_characters_compose",
    "_cmd_characters_list", "_cmd_characters_migrate_home", "_cmd_characters_payload_contract",
    "_cmd_characters_reopen", "_cmd_characters_reroll_direction", "_cmd_characters_reroll_row",
    "_cmd_characters_rows", "_cmd_characters_sprite", "_cmd_characters_start",
    "_cmd_characters_status", "_cmd_characters_thumb", "_cmd_characters_turnaround",
)})
LEDGER.update({name: _WORKSPACE_SLOTS_REASON for name in (
    "_cmd_workspace_slots_bind", "_cmd_workspace_slots_clone", "_cmd_workspace_slots_declare",
    "_cmd_workspace_slots_env_set", "_cmd_workspace_slots_report", "_cmd_workspace_slots_show",
)})
LEDGER.update({name: _PERSONA_SLOTS_REASON for name in ("_cmd_persona_slots_set", "_cmd_persona_slots_show")})
LEDGER.update(
    {
        # Emits through _mission_chat_emit. A chat SEND, not a read: the ack
        # names the session_id and persona_instance_id the turn ran under, so a
        # wrong root is a turn in a session the operator can name, never an
        # empty success. Its steer / queue-skill / turn-resolve siblings are above.
        "_cmd_mission_chat_message": "chat send: the ack names the session the turn ran in",
        # Emits through chat_target._close_free_floating_assignments, the body it
        # shares with _cmd_persona_instance_close (above): nothing to close is a
        # refusal (ok: false, exit 2), never an empty success.
        "_cmd_persona_instance_archive": "an empty answer is a refusal (ok: false), not ok: true",
    }
)
LEDGER.update(
    {
        # The snapshot frame carries the builder's OWN block —
        # ``parity.resolution`` (agent_runtime/snapshot.py) — for both the CLI
        # print and the serve/read-model cache lanes. A second top-level copy
        # of the same answer on the same wire would be the S48 duplication
        # class, so the verb is exempt rather than double-stamped. Pinned by
        # test_snapshot_frame_already_carries_parity_resolution below.
        "_cmd_snapshot": "frame carries parity.resolution from the builder",
        # ``verify`` packets have stated ``runtime_root`` / ``hermes_home`` /
        # ``hermes_profile`` at top level since inception — historically the
        # ONE verb that said which root it checked.
        "_cmd_verify": "packet already states runtime_root at top level",
    }
)


def _scan_files() -> list[Path]:
    return [_HARNESS_PY, *sorted(_PARTS_DIR.rglob("*.py"))]


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _handlers() -> dict[str, dict]:
    """Map handler name → {emits, attaches, chat_scope} for every ``_cmd_*``.

    ``emits`` is a REACHABILITY answer (D3.17): the handler's body reaches
    ``agent_runtime.cli_format.emit_json`` / ``emit_json_line`` through the
    calls the AST and each file's imports resolve, to a fixpoint over
    ``hermes_cli`` and ``agent_runtime`` (``tests/_downstream/call_graph.py``).
    A seam of any name — ``_print_stage42``, ``emit_operation_result``,
    ``_characters_emit``, ``_mission_chat_emit`` — emits because its body
    reaches the root. The hand-kept name set plus an ``_emit_*`` follow saw 123
    emitters; the graph sees 151, and the 28 it added are classified in the
    ledger above (each family read, none bulk-added).

    ``attaches`` / ``chat_scope`` keep the direct-call rules (``_ATTACH_CALL``,
    :data:`ATTACHING_DELEGATES`, held to a runtime proof below) and follow only
    the ``_emit_<verb>`` seams the R-C5 lowering (``13c1d67178``) introduced.
    Dynamic dispatch — a callable held in a table — is invisible to the graph,
    as it was to the name set; ``ATTACHING_DELEGATES`` is the door for it.
    """

    direct: dict[str, dict] = {}
    calls: dict[str, set[str]] = {}
    starts: dict[tuple[str, str], str] = {}
    for path in _scan_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = module_name(_REPO_ROOT, path)
        starts.update({(module, node.name): node.name for node in tree.body
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_cmd_")})
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (node.name.startswith("_cmd_") or node.name.startswith("_emit_")):
                continue
            attaches = chat_scope = False
            called: set[str] = set()
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                name = _call_name(sub)
                if name is None:
                    continue
                if name.startswith("_emit_"):
                    called.add(name)
                if name in ATTACHING_DELEGATES:
                    attaches = True
                    chat_scope = chat_scope or ATTACHING_DELEGATES[name]
                if name == _ATTACH_CALL:
                    attaches = True
                    for keyword in sub.keywords:
                        if (
                            keyword.arg == "chat_scope"
                            and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True
                        ):
                            chat_scope = True
            assert node.name not in direct or direct[node.name]["attaches"] == attaches, (
                f"duplicate handler name {node.name!r} with diverging shape — "
                "the name-keyed ledger below can no longer address it"
            )
            direct[node.name] = {"attaches": attaches, "chat_scope": chat_scope}
            calls[node.name] = called

    # Fixpoint rather than one hop: an ``_emit_*`` seam is free to delegate to
    # another one, and a cycle must not hang the scan.
    changed = True
    while changed:
        changed = False
        for name, called in calls.items():
            for target in called:
                if target == name or target not in direct:
                    continue
                for key in ("attaches", "chat_scope"):
                    if direct[target][key] and not direct[name][key]:
                        direct[name][key] = True
                        changed = True

    emitting = {starts[s] for s in CallGraph(_REPO_ROOT, _GRAPH_PACKAGES).reaching(_EMIT_ROOTS, starts)}
    return {
        name: {**info, "emits": name in emitting}
        for name, info in direct.items()
        if name.startswith("_cmd_")
    }


def test_every_json_verb_states_its_root_or_is_classified():
    handlers = _handlers()
    assert handlers, "AST scan found no _cmd_ handlers — the scan itself broke"

    unclassified = sorted(
        name
        for name, info in handlers.items()
        if info["emits"] and not info["attaches"] and name not in LEDGER
    )
    assert not unclassified, (
        "JSON-emitting harness verb(s) that state no runtime root and carry no "
        f"reviewed ledger reason: {unclassified}. A wrong root returns a "
        "well-formed EMPTY answer (ok: true, count: 0), so an envelope that "
        "does not say which root answered cannot be trusted when it is empty. "
        "Route the payload through "
        "agent_runtime.root_observability.attach_root_observability, or add a "
        "justified LEDGER entry in this test."
    )


def test_chat_lanes_stamp_chat_scope():
    handlers = _handlers()
    for name in sorted(CHAT_SCOPE_REQUIRED):
        info = handlers.get(name)
        assert info is not None, f"chat-lane handler {name!r} no longer exists"
        assert info["chat_scope"], (
            f"{name!r} must call {_ATTACH_CALL}(..., chat_scope=True): an empty "
            "chat read without chat_scope.source is the exact envelope the "
            "2026-08-12 incident could not distinguish from a lost transcript"
        )


def test_the_scan_sees_the_known_adopters():
    """Self-check against detection vacuity: if the attach predicate stops
    matching (rename, import shape change), this fails before the main gate
    silently passes every future verb."""

    handlers = _handlers()
    for name in ("_cmd_status", "_cmd_agent_list", "_cmd_doctor", "_cmd_persona_chat_history"):
        assert handlers.get(name, {}).get("attaches"), (
            f"{name!r} should be detected as attaching the resolution block — "
            "either it regressed or the scan's attach predicate broke"
        )


def test_the_scan_sees_the_known_emitters():
    """Positive control for the graph half: one handler per route to the JSON
    root — ``_print_stage42``, ``emit_operation_result`` (its only emitter), a
    named seam (``_characters_emit``), a shared helper body
    (``_close_free_floating_assignments``) and the stream line
    (``emit_json_line``). If resolution breaks, these go quiet first."""

    handlers = _handlers()
    for name in (
        "_cmd_board_card_add",
        "_cmd_persona_permission_set",
        "_cmd_characters_list",
        "_cmd_persona_instance_archive",
        "_cmd_characters_auto",
    ):
        assert handlers.get(name, {}).get("emits"), f"{name!r} should be detected as emitting JSON"


def test_every_attaching_delegate_attaches(monkeypatch, tmp_path):
    """The runtime half of :data:`ATTACHING_DELEGATES`: each delegate, called,
    returns an envelope that states its root — and its chat scope where the map
    claims one. Positive by construction: the stubs below return NO resolution
    block, so the keys can only come from the delegate's own attach."""

    import agent_runtime.realm_revert as realm_revert
    from agent_runtime import realm_sync, realm_verbs, store
    from tests._downstream.split_package_source import patch_where_bound
    from agent_runtime.chat_verbs.history import persona_chat_history_page

    monkeypatch.setattr(
        "agent_runtime.persona_chat_history.persona_chat_session_messages",
        lambda **kw: {"ok": True, "messages": [], "count": 0},
    )
    monkeypatch.setattr(realm_revert, "revert_realm_sync", lambda realm_id, **kw: {"reverted": []})
    monkeypatch.setattr("agent_runtime.realm_sync.realm_sync_status", lambda realm_id, **kw: {"id": realm_id})
    monkeypatch.setattr("agent_runtime.realm_sync.pull_realm_sync", lambda realm_id, **kw: {"id": realm_id})
    monkeypatch.setattr("agent_runtime.realm_sync.publish_realm_sync", lambda realm_id, **kw: {"id": realm_id})
    monkeypatch.setattr("agent_runtime.skill_sync.resolve_held_skill", lambda realm_id, key, **kw: {"id": key})
    patch_where_bound(monkeypatch, realm_sync, "realm_agent_selection_state",
                      lambda realm_id: {"required": [], "catalog": []})
    monkeypatch.setattr("agent_runtime.realm_membership.adopt_realms", lambda credential, **kw: [])

    class _Store:
        def get(self, realm_id):
            return realm_id

        def set_skill_selection(self, realm_id, **kw):
            return realm_id

        def set_agent_selection(self, realm_id, **kw):
            return None

    patch_where_bound(monkeypatch, store, "RealmStore", _Store)
    monkeypatch.setattr(realm_verbs, "realm_skill_selection_envelope", lambda realm: {"id": realm})
    produced = {
        "persona_chat_history_page": persona_chat_history_page("s1"),
        "realm_sync_revert": realm_verbs.realm_sync_revert("realm_x"),
        "realm_sync_status": realm_verbs.realm_sync_status("realm_x"),
        "realm_sync_pull": realm_verbs.realm_sync_pull("realm_x"),
        "realm_sync_publish": realm_verbs.realm_sync_publish("realm_x"),
        "realm_sync_resolve": realm_verbs.realm_sync_resolve("realm_x", key="skill::a", take="realm"),
        "realm_skills_show": realm_verbs.realm_skills_show("realm_x"),
        "realm_skills_set": realm_verbs.realm_skills_set("realm_x", publish_all=True),
        "realm_agents_show": realm_verbs.realm_agents_show("realm_x"),
        "realm_agents_set": realm_verbs.realm_agents_set("realm_x", publish_workspace=True),
        "realm_adopt": realm_verbs.realm_adopt(object()),
    }
    assert set(produced) == set(ATTACHING_DELEGATES)
    for name, envelope in produced.items():
        assert "resolution" in envelope, f"{name} no longer attaches the resolution block"
        assert ("chat_scope" in envelope) is ATTACHING_DELEGATES[name], name


def test_ledger_does_not_rot():
    """Every ledger entry must still name a real, JSON-emitting handler that
    still lacks the attach call — otherwise the entry is stale and must go."""

    handlers = _handlers()
    for name in LEDGER:
        info = handlers.get(name)
        assert info is not None, f"LEDGER entry {name!r} names no handler — remove it"
        assert info["emits"], f"LEDGER entry {name!r} no longer emits JSON — remove it"
        assert not info["attaches"], (
            f"LEDGER entry {name!r} now attaches the resolution block — remove "
            "the stale exemption"
        )


def test_snapshot_frame_already_carries_parity_resolution():
    """The ``_cmd_snapshot`` ledger reason is a claim about the producer; pin
    it at the producer so the exemption cannot outlive the block."""

    # The snapshot builder is a package since lane R3; its modules read as one text.
    import agent_runtime.snapshot as snapshot_package
    from tests._downstream.split_package_source import package_source

    snapshot_source = package_source(snapshot_package)
    tree = ast.parse(snapshot_source)
    stamped = any(
        isinstance(node, ast.Dict)
        and any(
            isinstance(key, ast.Constant) and key.value == "resolution"
            for key in node.keys
        )
        for node in ast.walk(tree)
    )
    assert stamped, (
        "agent_runtime/snapshot.py no longer stamps a 'resolution' key — the "
        "_cmd_snapshot LEDGER exemption is stale; attach the block in the verb"
    )
