"""Persona instance retirement and the chat-pointer writer fences.

Split from one 5,169-line file so the per-file runner parallelises it
(FH-PREPUSH-TOUCHED-OVER-BUDGET-PERSONA-ASSIGNMENTS); shared helpers live in
``tests/agent_runtime/persona_assignments_helpers.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.events import EventLog
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_history import persona_chat_history_summary
from agent_runtime.snapshot import build_snapshot
from hermes_cli.harness_parts.persona import (
    chat_delete,
    chat_open,
    instance_commands,
    lifecycle_commands,
)
from tests.agent_runtime.persona_assignments_helpers import (
    _assignment_config,
    _persona,
    _seed_run,
    _TranscriptDB,
)

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


# ---------------------------------------------------------------------------
# Instance end-of-life: `harness persona instance retire` (placement removal).
# The operator ruling — deleting a deliberate placement IS the instance's
# end-of-life — needs a sanctioned verb that archives the ROW (not an
# assignment), emits an evented mutation, guards a working agent, and drops the
# row from every instance-fed projection while leaving chat history on disk.
# ---------------------------------------------------------------------------


def _placement_instance(persona_id: str = "dev", placement_id: str = "scene_child_2_agent_1", display_name: str = "Dev (2)") -> PersonaInstance:
    return PersonaInstanceStore().add_instance(
        persona_id=persona_id,
        placement_id=placement_id,
        display_name=display_name,
    )


def test_retire_archives_placement_row_and_emits_event(isolate_agent_runtime_root):
    from agent_runtime import paths

    store = PersonaInstanceStore()
    instance = _placement_instance()
    assert instance.id == "personainst_scene_child_2_agent_1"
    session_id = instance.session_id
    assert session_id  # a real chat session pointer we must NOT destroy

    result = store.retire(instance.id, reason="placement deleted", requested_by="operator")

    # Row left the live dir ...
    assert not paths.persona_instance_path(instance.id).exists()
    assert instance.id not in {row.id for row in store.list_all()}
    # ... and landed in the archive (never deleted); its session pointer survives.
    # The receipts subdirectory is excluded, because it does not hold ROWS. H-H5
    # writes the retire's own outcome to ``<ts>_retire/receipts/<id>.json`` —
    # the same basename, one directory down — so this recursive glob began
    # answering 2 for a single archived row. The guarantee here was always "the
    # row landed exactly once and was never deleted", and a receipt is not a
    # row; the repair is to say which files count, not to loosen the count.
    # Every PRODUCTION reader of this archive already excludes it structurally,
    # by exact child path (``_retired_persona_instance_archive_path``) or by a
    # non-recursive ``*.json`` glob inside the batch
    # (``retired_persona_instance_ids``) — which is the whole reason the receipt
    # lives in a subdirectory rather than beside the row, where it would have
    # minted a phantom retirement tombstone.
    archived = [
        path
        for path in paths.persona_instances_archive_dir().rglob(f"{instance.id}.json")
        if path.parent.name != "receipts"
    ]
    assert len(archived) == 1
    archived_payload = json.loads(archived[0].read_text(encoding="utf-8"))
    assert archived_payload["session_id"] == session_id
    assert Path(result["archive_path"]) == archived[0]
    assert result["persona_id"] == "dev"

    events = [event for event in EventLog().tail(50) if event.type == "persona_instance.retired"]
    assert len(events) == 1
    payload = events[0].payload
    assert payload["persona_instance_id"] == instance.id
    assert payload["reason"] == "placement deleted"
    assert payload["requested_by"] == "operator"
    assert payload["persona_id"] == "dev"


def test_retire_releases_child_backlinks_without_clearing_child_context(
    isolate_agent_runtime_root,
):
    store = PersonaInstanceStore()
    retiring = _placement_instance(
        persona_id="neko_supervisor",
        placement_id="lead_retiring_agent_2",
        display_name="Retiring lead",
    )
    remaining = _placement_instance(
        persona_id="neko_supervisor",
        placement_id="lead_remaining_agent_2",
        display_name="Remaining lead",
    )
    child = _placement_instance(
        persona_id="dev",
        placement_id="dev_child_agent_2",
        display_name="Dev child",
    )
    child = store.set_parents(
        child.id,
        [retiring.id, remaining.id],
        goal_id="goal_live",
    )

    store.retire(retiring.id, reason="placement deleted")

    child = store.get(child.id)
    assert child.steered_by == [remaining.id]
    assert child.spawned_by == remaining.id
    assert child.goal_id == "goal_live"
    # The goal is a correlation id, never a task binding (RT-TASK-BOUND-VOCABULARY).
    assert child.current_task_id is None
    assert child.mode != "task_bound"


def test_retire_last_parent_preserves_child_mission_context(
    isolate_agent_runtime_root,
):
    store = PersonaInstanceStore()
    retiring = _placement_instance(
        persona_id="neko_supervisor",
        placement_id="lead_only_agent_2",
        display_name="Only lead",
    )
    child = _placement_instance(
        persona_id="dev",
        placement_id="dev_only_child_agent_2",
        display_name="Dev child",
    )
    child = store.set_parents(child.id, [retiring.id], goal_id="goal_live")

    store.retire(retiring.id, reason="placement deleted")

    child = store.get(child.id)
    assert child.steered_by == []
    assert child.spawned_by is None
    assert child.goal_id == "goal_live"
    # The goal is a correlation id, never a task binding (RT-TASK-BOUND-VOCABULARY).
    assert child.current_task_id is None
    assert child.mode != "task_bound"


def test_retired_placement_cannot_be_resurrected_from_its_saved_chat(
    isolate_agent_runtime_root,
):
    from agent_runtime import paths
    from agent_runtime.persona_assignments import RetiredPersonaInstanceError

    store = PersonaInstanceStore()
    instance = _placement_instance(placement_id="dev_agent_2")
    session_id = instance.session_id
    assert session_id

    result = store.retire(instance.id, reason="placement deleted")

    with pytest.raises(RetiredPersonaInstanceError) as excinfo:
        store.open_chat(
            persona_id=instance.persona_id,
            persona_instance_id=instance.id,
            session_id=session_id,
        )

    assert excinfo.value.persona_instance_id == instance.id
    assert excinfo.value.archive_path == Path(result["archive_path"])
    assert not paths.persona_instance_path(instance.id).exists()
    assert instance.id not in {row.id for row in store.list_all()}


def test_retirement_is_answerable_read_only_before_anything_is_written(
    isolate_agent_runtime_root,
):
    """``open_chat`` answers "is this target retired?" only by RAISING, which is
    too late for a caller whose durable writes come first (the chat mint created
    and titled a session row, then bound). The same rule — no live row PLUS a
    ``*_retire`` tombstone — is available as a read-only predicate, and the rule
    itself has exactly one home: ``open_chat`` asks the predicate too."""

    store = PersonaInstanceStore()
    live = _placement_instance(placement_id="dev_agent_3")
    retired = _placement_instance(placement_id="dev_agent_2")
    result = store.retire(retired.id, reason="placement deleted")

    assert str(store.retired_instance_archive_path(retired.id)) == result["archive_path"]
    # A live placement is never a tombstone, and neither is an id that never
    # existed — retirement is absence PLUS a tombstone, not absence alone, or
    # every first-ever mint in the product would refuse.
    assert store.retired_instance_archive_path(live.id) is None
    assert store.retired_instance_archive_path("personainst_never_placed") is None
    assert store.retired_instance_archive_path(None) is None
    # The predicate is READ-ONLY: asking must not resurrect, create, or evict.
    assert {row.id for row in store.list_all()} == {live.id}
    # ``persona_id`` resolves a caller-supplied id through the same derivation
    # ``open_chat`` uses, so a drifted actor token gets the same answer.
    assert str(
        store.retired_instance_archive_path(f"persona_{retired.id}", persona_id="dev")
    ) == result["archive_path"]


def test_a_live_row_outranks_a_stale_retire_tombstone_for_the_same_id(
    isolate_agent_runtime_root,
):
    """The predicate's live-row-wins branch, pinned on a CONSTRUCTED state.

    No public verb can produce this state today: ``retire`` archives the row in
    the same breath as it writes the tombstone, so live-row-AND-tombstone is
    unreachable through the store's API — which is exactly why this branch
    survives every realistic scenario untested and reads like dead weight to
    the next person holding a knife.

    It is armor for the verb this design invites next. Tombstones are permanent,
    so an un-retire / re-placement that writes an id back into the live roster
    would leave precisely this shape behind — and a predicate that consulted
    only the archive would then call that live placement retired and refuse
    every chat it ever opened. So the state is built by hand: the archived row
    put back on disk, the tombstone deliberately left where it is.
    """

    from agent_runtime import paths

    store = PersonaInstanceStore()
    retired = _placement_instance(placement_id="dev_agent_2")
    result = store.retire(retired.id, reason="placement deleted")
    tombstone = Path(result["archive_path"])
    assert str(store.retired_instance_archive_path(retired.id)) == result["archive_path"]

    live_path = paths.persona_instance_path(retired.id)
    live_path.parent.mkdir(parents=True, exist_ok=True)
    live_path.write_text(tombstone.read_text(encoding="utf-8"), encoding="utf-8")

    # Both facts hold at once now, and the LIVE one is the one that decides.
    assert store.get(retired.id).id == retired.id
    assert tombstone.is_file(), "the tombstone must survive for this to prove anything"
    assert store.retired_instance_archive_path(retired.id) is None

def test_assert_bindable_answers_the_binds_refusals_without_writing(
    isolate_agent_runtime_root,
):
    """The seam that lets a lane refuse BEFORE its first durable write.

    ``open_chat`` answers "may this bind happen?" only by raising at the end
    of whatever the caller already did, which is why a mint could reach it
    with a titled session row already on disk. Same refusals, same typed
    error, same canonical target id — asserted without touching the store."""

    from agent_runtime import paths
    from agent_runtime.persona_assignments import RetiredPersonaInstanceError

    store = PersonaInstanceStore()
    live = _placement_instance(placement_id="dev_agent_2")

    # A live placement is bindable, and the canonical id comes back once.
    assert store.assert_bindable(persona_id="dev", persona_instance_id=live.id) == live.id
    # A first-ever canonical channel is bindable too: retirement is the
    # ABSENCE of a live row PLUS a tombstone, never absence alone.
    assert store.assert_bindable(persona_id="qa") == "personainst_qa"
    assert not paths.persona_instance_path("personainst_qa").exists()

    # A sibling's session is the same ValueError the bind raises.
    with pytest.raises(ValueError):
        store.assert_bindable(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id=f"persona_chat_{live.id}_abcdef123456",
        )

    archived = store.retire(live.id, reason="placement deleted")
    with pytest.raises(RetiredPersonaInstanceError) as excinfo:
        store.assert_bindable(persona_id="dev", persona_instance_id=live.id)
    assert excinfo.value.persona_instance_id == live.id
    assert str(excinfo.value.archive_path) == archived["archive_path"]
    # …and the refusal never revived the row it refused.
    assert live.id not in {row.id for row in PersonaInstanceStore().list_all()}


def test_open_chat_cli_reports_a_retired_root_as_retired_not_unknown(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    instance = _placement_instance(placement_id="dev_agent_2")
    session_id = instance.session_id
    assert session_id
    PersonaInstanceStore().retire(instance.id, reason="placement deleted")

    code = chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id=instance.persona_id,
            session_id=session_id,
            add_instance=False,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    # `retired_persona_instance`, not `unknown_chat_session`. Retiring a
    # placement archives the row and deliberately PRESERVES its chat on disk,
    # so re-opening that thread has a typed end-of-life answer: the tombstone
    # path and "history preserved". "unknown chat session" named the wrong
    # fact (the root is known; its owner ended) and offered the wrong next
    # step. The genuinely-unknown case is a different case, pinned below.
    assert payload["persona_instance_id"] == instance.id
    assert payload["history_preserved"] is True
    assert payload["error_kind"] == "retired_persona_instance"
    assert instance.id not in {
        row.id for row in PersonaInstanceStore().list_all()
    }


def test_open_chat_cli_still_rejects_a_genuinely_unknown_root(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    """The case `unknown_chat_session` is actually for, kept distinct.

    A LIVE instance whose named root was never persisted: nothing was
    retired, nothing has an archive to point at, and "open a server-minted
    chat root before sending" is the right next step. The retirement
    pre-flight must not swallow it."""

    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    instance = _placement_instance(placement_id="dev_agent_3")
    assert instance.id in {row.id for row in PersonaInstanceStore().list_all()}

    code = chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id=instance.persona_id,
            session_id=f"persona_chat_{instance.id}_abcdef123456",
            add_instance=False,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_kind"] == "unknown_chat_session"


def test_retire_refuses_canonical_persona_channel(isolate_agent_runtime_root):
    from agent_runtime import paths
    from agent_runtime.persona_assignments import PersonaInstanceRetireError

    store = PersonaInstanceStore()
    canonical = store.ensure_for_persona(_persona("dev"))
    assert canonical.id == "personainst_dev"

    with pytest.raises(PersonaInstanceRetireError) as excinfo:
        store.retire(canonical.id)
    assert excinfo.value.code == "canonical_persona_channel"
    # Refusal is a no-op: the canonical channel stays live on disk.
    assert paths.persona_instance_path(canonical.id).exists()
    assert canonical.id in {row.id for row in store.list_all()}


def test_retire_refuses_active_run_binding(isolate_agent_runtime_root):
    from agent_runtime import paths
    from agent_runtime.persona_assignments import PersonaInstanceRetireError

    store = PersonaInstanceStore()
    instance = _placement_instance()
    run = _seed_run("dev", "task_live", "stage_1", session_id="session_live")
    instance.active_run_id = run.id
    store.update(instance)

    with pytest.raises(PersonaInstanceRetireError) as excinfo:
        store.retire(instance.id)
    assert excinfo.value.code == "instance_active"
    assert excinfo.value.detail["active_run_id"] == run.id
    assert paths.persona_instance_path(instance.id).exists()


def test_retire_refuses_missing_instance(isolate_agent_runtime_root):
    from agent_runtime.persona_assignments import PersonaInstanceRetireError

    with pytest.raises(PersonaInstanceRetireError) as excinfo:
        PersonaInstanceStore().retire("personainst_does_not_exist")
    assert excinfo.value.code == "not_found"


def test_retire_excludes_instance_from_snapshot_projection(monkeypatch, isolate_agent_runtime_root):
    cfg = _assignment_config()
    monkeypatch.setattr("agent_runtime.snapshot.envelope.load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr("agent_runtime.snapshot.sections.load_agent_runtime_config", lambda: cfg)
    store = PersonaInstanceStore()
    instance = _placement_instance()

    before = build_snapshot()
    assert instance.id in before["persona_instances"]

    store.retire(instance.id, reason="placement deleted")

    after = build_snapshot()
    assert instance.id not in after["persona_instances"]
    # The chat-history projection reads the live instances, so it drops too.
    history = persona_chat_history_summary(persona_instances=store.list_all())
    assert instance.id not in {row.get("persona_instance_id") for row in history}


def test_retire_cli_happy_path_archives_row(monkeypatch, isolate_agent_runtime_root):
    from argparse import Namespace

    from agent_runtime import paths

    cfg = _assignment_config()
    monkeypatch.setattr(instance_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    instance = _placement_instance()

    code = instance_commands._cmd_persona_instance_retire(
        Namespace(
            persona_instance_id=instance.id,
            reason="placement deleted",
            requested_by="operator",
            coordinator_id=None,
            coordinator_max_spawns=None,
            coordinator_spawns_used=0,
            coordinator_may_kill_own=None,
            coordinator_no_kill_own=None,
            coordinator_may_kill_others=None,
            json=True,
        )
    )

    assert code == 0
    assert not paths.persona_instance_path(instance.id).exists()
    assert instance.id not in {row.id for row in PersonaInstanceStore().list_all()}


def test_retire_cli_canonical_refusal_returns_typed_error(monkeypatch, capsys, isolate_agent_runtime_root):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(instance_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    canonical = PersonaInstanceStore().ensure_for_persona(_persona("dev"))

    code = instance_commands._cmd_persona_instance_retire(
        Namespace(
            persona_instance_id=canonical.id,
            reason="placement deleted",
            requested_by="operator",
            coordinator_id=None,
            coordinator_max_spawns=None,
            coordinator_spawns_used=0,
            coordinator_may_kill_own=None,
            coordinator_no_kill_own=None,
            coordinator_may_kill_others=None,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "canonical_persona_channel"
    assert payload["persona_instance_id"] == canonical.id


def test_retire_cli_coordinator_operator_placed_needs_confirm(monkeypatch, capsys, isolate_agent_runtime_root):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(instance_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    # A placement dropped by the operator is not owned by a coordinator, so a
    # coordinator cannot end-of-life it (KILL_ACTIONS gate -> operator confirm).
    instance = _placement_instance()

    code = instance_commands._cmd_persona_instance_retire(
        Namespace(
            persona_instance_id=instance.id,
            reason="coordinator tried retiring operator placement",
            requested_by="coordinator:neko_supervisor",
            coordinator_id="neko_supervisor",
            coordinator_max_spawns=0,
            coordinator_spawns_used=0,
            coordinator_may_kill_own=True,
            coordinator_no_kill_own=None,
            coordinator_may_kill_others=True,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "needs_operator_confirm"


# ── how many paths may move an instance's chat pointers ─────────────────────
#
# ``clear_chat_session_binding`` used to claim "every unbind … goes through
# here so a stale binding can never be cleared silently by one path and loudly
# by another". Since ``b912cce88a`` that was false: ``rollback_chat_root_bind``
# nulls the same two fields and emits no ``chat_binding_cleared``.
#
# The claim was corrected rather than made true, because the retraction cannot
# route through the clear without losing three properties it needs (restores
# instead of clearing, must not raise inside a failure handler, must emit a
# ``state.patched`` the clear does not emit) — the argument is spelled out in
# ``clear_chat_session_binding``'s docstring.
#
# A corrected sentence is only worth what enforces it, so this is the fence: a
# prose claim about "two paths" is checkable only if the count is checked. It
# reads the module's AST rather than grepping, so a rename or a reformat does
# not silently widen it.


def _chat_pointer_writers() -> dict[str, set[str]]:
    """Every function in ``persona_assignments`` that assigns a chat pointer.

    Maps function name -> the pointer fields it writes. Attribute targets only
    (``<something>.default_chat_session_id = …``): the local rebinds inside the
    module's own helpers are not writes to a row.
    """

    import ast

    from agent_runtime import persona_assignments

    pointers = {"default_chat_session_id", "session_id"}
    # The package's modules, each parsed on its own (the file became a package).
    package_dir = Path(persona_assignments.__file__).parent
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in sorted(package_dir.glob("*.py"))]
    writers: dict[str, set[str]] = {}
    for node in (node for tree in trees for node in ast.walk(tree)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            # ``AnnAssign``/``AugAssign`` too, not just ``Assign``: a gate that
            # only recognises one assignment node is a gate a third path walks
            # past by writing ``instance.session_id: str | None = None``.
            if isinstance(inner, ast.Assign):
                targets = list(inner.targets)
            elif isinstance(inner, (ast.AnnAssign, ast.AugAssign)):
                targets = [inner.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in pointers:
                    writers.setdefault(node.name, set()).add(target.attr)
    return writers


def test_only_two_paths_may_move_an_instances_chat_pointers():
    """One bind, one clear, one restore — and the module says which is which.

    If a THIRD unbind path appears, this fails and names it. That is the whole
    point: the docstring in ``clear_chat_session_binding`` now enumerates the
    exception instead of denying it, and an enumeration nobody counts drifts
    back into the sentence it replaced within one commit.

    A new writer is not automatically wrong — it is unreviewed. The cure is to
    decide whether it belongs behind ``clear_chat_session_binding`` (a stale
    binding being reaped) or beside ``rollback_chat_root_bind`` (a bind this
    same lane made being retracted), say so in that docstring, and add it here.
    """

    assert _chat_pointer_writers() == {
        # THE bind. Writes both pointers to the root it is opening.
        "open_chat": {"default_chat_session_id", "session_id"},
        # THE clear: nulls only pointers matching one session id, demotes the
        # mode, and emits ``persona_instance.chat_binding_cleared``.
        "clear_chat_session_binding": {"default_chat_session_id", "session_id"},
        # THE retraction: restores the pre-bind values (which may be ``None``),
        # keyed on the root identity it bound, and never raises.
        "rollback_chat_root_bind": {"default_chat_session_id", "session_id"},
    }


def test_the_two_unbind_paths_are_told_apart_by_what_they_emit():
    """The reason they are allowed to stay separate, pinned as behaviour.

    ``clear_chat_session_binding`` emits the domain event and NO
    ``state.patched`` (``_event`` only appends to the log). The retraction emits
    ``emit_persona_instance_patch`` and no domain event. Routing either through
    the other silently changes what every connected launcher receives, so the
    difference is asserted here rather than left as an assurance in a comment.

    This is the SOURCE half of the difference. The tests at the bottom of
    this file are the WIRE half -- what each shape actually costs a
    connected client -- because a source grep cannot tell a deliberate
    omission from a missing producer, and the question this asymmetry
    provokes ("is the clear leaving every launcher stale?") is answerable
    only from a run. It is not: the clear's event is uncovered, so its
    batch ships the whole core.
    """

    import inspect

    from agent_runtime.persona_assignments import PersonaInstanceStore

    clear = inspect.getsource(PersonaInstanceStore.clear_chat_session_binding)
    retract = inspect.getsource(PersonaInstanceStore.rollback_chat_root_bind)

    body_of = lambda src: src.split('"""', 2)[-1]  # drop the docstring

    assert "chat_binding_cleared" in body_of(clear)
    assert "emit_persona_instance_patch" not in body_of(clear)

    assert "emit_persona_instance_patch" in body_of(retract)
    assert "chat_binding_cleared" not in body_of(retract)


# -- what each unbind path costs a CONNECTED client --------------------------
#
# The source-level difference above was read as a defect: the clear moves
# ``mode`` and the session trio on ``persona_instance_summary`` and emits no
# ``state.patched``, so "every connected launcher keeps rendering the chat
# pointer the store no longer holds until a full snapshot refresh". Driven,
# that is not what happens -- the full snapshot refresh arrives in the SAME
# frame, because the event the clear does emit is uncovered and demotes its own
# batch. The tests below pin that, and pin the reason it must stay that way, so
# the next reader of the source-level asymmetry gets the measurement instead of
# re-deriving the wrong conclusion from it.


def _batch_since(offset: int):
    return list(EventLog().iter_from_offset(0))[offset:]


def _frames_for(batch, *, base_offset: int, delta_patches: bool = True):
    from agent_runtime import stream as stream_mod

    return list(
        stream_mod._batch_frames_with_liveness(
            batch,
            base_offset=base_offset,
            delta_patches=delta_patches,
            resync=False,
            heartbeat_interval_seconds=5.0,
            fold_entities=None,
        )
    )


def test_a_cleared_binding_is_not_stale_because_its_own_event_demotes_the_batch(
    isolate_agent_runtime_root,
):
    """The clear ships the whole core, so there is nothing left stale to patch.

    ``persona_instance.chat_binding_cleared`` is deliberately outside
    ``patch_coverage.COVERED_DOMAIN_EVENT_TYPES``, and one uncovered event makes
    the entire coalesced batch uncoverable. The frame a connected client
    receives therefore carries a full ``core`` and no ``patches`` list at all --
    the row is re-hydrated in the same frame that reports the clear.

    A ``state.patched`` emitted here would be unreachable: the promotion gate
    rejects the batch before the patches list is assembled. That is why
    ``clear_chat_session_binding`` emits none, and this is the assertion that
    keeps "it emits no patch" from drifting back into "it leaves clients stale".
    """

    from agent_runtime.patch_coverage import (
        COVERED_DOMAIN_EVENT_TYPES,
        batch_is_patch_coverable,
    )

    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="dev", session_id="persona_chat_clear_wire")
    base = len(list(EventLog().iter_from_offset(0)))

    record = store.clear_chat_session_binding(
        instance, session_id="persona_chat_clear_wire", reason="chat_deleted"
    )
    assert record is not None

    batch = _batch_since(base)
    assert [event.type for _, event in batch] == [
        "persona_instance.chat_binding_cleared"
    ]
    assert "persona_instance.chat_binding_cleared" not in COVERED_DOMAIN_EVENT_TYPES
    assert not batch_is_patch_coverable(event for _, event in batch), (
        "the clear's batch became patch-coverable; a connected client will now "
        "fold a field subset instead of re-hydrating, and the clear moves core "
        "state no persona_instance patch can express (see the chat-history test)"
    )

    frames = _frames_for(batch, base_offset=base)
    assert [frame.get("type") for frame in frames] == ["delta"]
    assert frames[0].get("patches") is None
    assert isinstance(frames[0].get("core"), dict), (
        "the clear stopped shipping a full core; the row it moved now reaches "
        "no connected client at all"
    )
    # The re-hydrated core carries the CLEARED row, which is the whole reason
    # this path needs no patch of its own.
    rebuilt = frames[0]["core"]["persona_instances"][instance.id]
    assert rebuilt["default_chat_session_id"] is None
    assert rebuilt["session_id"] is None
    assert rebuilt["mode"] == "configured"


def test_covering_the_clear_would_drop_the_chat_history_row_it_also_moves(
    isolate_agent_runtime_root,
):
    """Why the demote is load-bearing rather than an un-done optimisation.

    A clear does not only move ``persona_instance`` fields. The
    ``persona_chat_history`` projection keys chat rows by
    ``default_chat_session_id``, so nulling the pointer takes the instance's
    chat row OUT of the section entirely -- and there is no
    ``persona_chat_history`` patch entity for that departure to ride.

    So the tempting symmetry with ``persona_instance.chat_opened`` (emit a
    patch, add the event to the covered set, stop paying a full core per chat
    delete) is a trade this wire cannot make yet: the promoted frame's only row
    would be the persona-instance patch, and the chat row would sit on every
    connected client for the rest of its session. The measurement is here so the
    next person to notice the asymmetry finds the reason instead of the gap.
    """

    from agent_runtime.patch_coverage import (
        COVERED_DOMAIN_EVENT_TYPES,
        HISTORICAL_FOLD_ENTITIES,
        normalize_fold_entities,
    )

    db = _TranscriptDB()
    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="dev", session_id="persona_chat_history_move")
    db.create_session("persona_chat_history_move", "agent_runtime_persona_chat")

    before = persona_chat_history_summary(
        persona_instances=[store.get(instance.id)],
        session_db=db,
    )
    assert [row["session_id"] for row in before] == ["persona_chat_history_move"]

    store.clear_chat_session_binding(
        store.get(instance.id),
        session_id="persona_chat_history_move",
        reason="chat_deleted",
    )

    after = persona_chat_history_summary(
        persona_instances=[store.get(instance.id)],
        session_db=db,
    )
    assert after == [], (
        "the chat-history row survived the clear; if that is now true the "
        "derivability argument below has changed and must be re-audited"
    )

    # Nothing a fielded client folds can carry that departure incrementally...
    declared = normalize_fold_entities(None)
    assert declared == normalize_fold_entities(HISTORICAL_FOLD_ENTITIES)
    assert "persona_chat_history" not in declared
    # ...so the event must stay uncovered, or the row is dropped silently.
    assert "persona_instance.chat_binding_cleared" not in COVERED_DOMAIN_EVENT_TYPES, (
        "the clear's event was added to the covered set, but its "
        "persona_chat_history row still has no patch entity to ride -- a "
        "promoted batch drops the chat row from every connected client"
    )


def test_both_live_clear_callers_reach_a_client_through_the_full_core(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    """The delete verb and the reconcile sweep, each driven, each demoting.

    Two operator-visible callers reach ``clear_chat_session_binding``. Neither
    is a special case: both append the same uncovered event, so both re-hydrate
    the client in the frame that reports the clear. A caller that emitted a
    patch INSTEAD of the event would pass the source-level test above and fail
    here, which is the point of driving them rather than asserting the shared
    code path.
    """

    from agent_runtime.patch_coverage import batch_is_patch_coverable

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    store = PersonaInstanceStore()

    # -- caller 1: the operator ``persona chat delete`` verb -----------------
    deleted = store.create_operator_chat(
        persona_id="profile_reviewer", display_name="Reviewer"
    )
    db.create_session(deleted.session_id, "agent_runtime_persona_chat")
    base = len(list(EventLog().iter_from_offset(0)))
    assert (
        chat_delete._cmd_persona_chat_delete(
            SimpleNamespace(
                session_id=deleted.session_id,
                persona_id=deleted.persona_id,
                persona_instance_id=deleted.id,
                requested_by="test",
                json=True,
            )
        )
        == 0
    )
    capsys.readouterr()
    delete_batch = _batch_since(base)
    assert "persona_instance.chat_binding_cleared" in {
        event.type for _, event in delete_batch
    }
    assert not batch_is_patch_coverable(event for _, event in delete_batch)
    frames = _frames_for(delete_batch, base_offset=base)
    assert frames and all(isinstance(frame.get("core"), dict) for frame in frames)

    # -- caller 2: the reconcile sweep ---------------------------------------
    orphan = store.open_chat(persona_id="qa", session_id="persona_chat_orphaned_root")
    # The sweep clears only on a POSITIVE "absent" from an enumerating
    # SessionDB, so the probe must see a live database that simply does not
    # hold this root.
    db.create_session("persona_chat_unrelated_live", "agent_runtime_persona_chat")
    base = len(list(EventLog().iter_from_offset(0)))
    result = PersonaInstanceStore().repair_missing_chat_session_bindings(
        apply=True, session_db=db
    )
    assert orphan.id in {row["persona_instance_id"] for row in result["repaired"]}
    sweep_batch = _batch_since(base)
    assert "persona_instance.chat_binding_cleared" in {
        event.type for _, event in sweep_batch
    }
    assert not batch_is_patch_coverable(event for _, event in sweep_batch)
    frames = _frames_for(sweep_batch, base_offset=base)
    assert frames and all(isinstance(frame.get("core"), dict) for frame in frames)


def test_persona_chat_delete_takes_the_compression_lineage_with_a_real_session_db(
    monkeypatch, capsys, isolate_agent_runtime_root, tmp_path
):
    """A real SessionDB goes through ``session_extensions.delete_compression_lineage``:
    the root's compression continuation leaves with it, an explicit branch stays."""
    from hermes_state import SessionDB

    cfg = _assignment_config()
    db = SessionDB(tmp_path / "state.db")
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    instance = PersonaInstanceStore().create_operator_chat(
        persona_id="profile_reviewer",
        display_name="Reviewer",
    )
    root = instance.session_id
    db.create_session(root, "agent_runtime_persona_chat")
    db.end_session(root, "compression")
    db.create_session("tip", "agent_runtime_persona_chat", parent_session_id=root)
    db.create_session("branch", "agent_runtime_persona_chat", parent_session_id=root,
                      model_config={"_branched_from": root})

    code = chat_delete._cmd_persona_chat_delete(
        SimpleNamespace(
            session_id=root,
            persona_id=instance.persona_id,
            persona_instance_id=instance.id,
            requested_by="test",
            json=True,
        )
    )

    assert code == 0, capsys.readouterr()
    assert db.get_session(root) is None
    assert db.get_session("tip") is None
    assert db.get_session("branch")["parent_session_id"] is None
