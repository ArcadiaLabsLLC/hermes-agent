"""When an owed realm re-key runs and what makes it wait (``agent_runtime.realm_rekey_triggers``,
RT-REKEY-RUNS-WHEN-IDLE-AND-AT-START; plan ``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md`` §5).

The realm is the census test's: real stores, a bare team repository, a real leave, a local-era sync. The busy
facts are the real ones (an admitted turn, a Work run record on disk, the workspace-writer lock, a rename the
OS refuses); a build and a second serve are stood in at the one function that lists them. Killing mutations
are named per test."""
import threading
import time
import types
from pathlib import Path

import pytest

from agent_runtime import realm_rekey_triggers as triggers
from agent_runtime import turn_activity
from agent_runtime.profile_runner import workdir
from agent_runtime.realm_rekey import RekeyState, owe_rekey, read_rekey_journal
from agent_runtime.realm_rekey_triggers import RekeyBusy, RekeyTrigger
from agent_runtime.realm_sync import RealmSyncError
from agent_runtime.store import RealmStore, WorkspaceStore
from agent_runtime.work_store import engine
from agent_runtime.work_store.grammar import RowRef
from tests.agent_runtime.test_realm_rekey_census import HELPER, _left_realm


def _state(realm_id: str) -> str:
    return read_rekey_journal(realm_id)["state"]


def _work_run(workspace_id: str, state: engine.RecordState) -> engine.RunRecord:
    record = engine.RunRecord(
        request_id=f"req_{workspace_id}", ref=RowRef("brain", "queue.md", "ROW-1"), workspace_id=workspace_id,
        persona_instance_id=HELPER, root_session_id="root", client_message_id="msg",
        started_at="2026-11-12T00:00:00+00:00", state=state)
    engine._save(record)
    return record


def test_an_owed_rekey_waits_for_a_turn_a_work_run_a_build_and_another_serve_then_runs(tmp_path, monkeypatch):
    """Mutations: drop ``_a_turn_is_running`` from BUSY_FACTS -> the re-key runs under an admitted turn, red;
    read Work runs of every workspace (drop ``record.workspace_id in workspaces``) -> the neighbour's run holds
    this realm, red; count a settled run as open -> red at the neighbour step's twin below; drop the
    ``os.getpid()`` exclusion -> a serve waits on itself, red; drop the non-blocking take of the
    workspace-writer lock -> the re-key runs while a restore holds it, red."""
    realm, first, _second, _extra, _head = _left_realm(tmp_path)
    owe_rekey(realm.id, reason="membership_left")
    assert triggers.pending_rekeys() == [realm.id]

    with turn_activity.admitted_turn("turn_1"):
        assert [(a.realm_id, a.busy) for a in triggers.run_owed_rekeys(RekeyTrigger.IDLE)] == [(realm.id, RekeyBusy.TURN)]
    assert _state(realm.id) == RekeyState.OWED.value

    neighbour = WorkspaceStore().get("ws_shared_2")
    settled, theirs = _work_run(first.id, engine.RecordState.SETTLED), _work_run(neighbour.id, engine.RecordState.RUNNING)
    assert triggers.busy_fact(read_rekey_journal(realm.id)["map"]) is None  # a settled run, and another realm's
    engine._drop(settled)
    mine = _work_run(first.id, engine.RecordState.RUNNING)
    assert triggers.try_rekey(realm.id).busy is RekeyBusy.WORK_RUN
    engine._drop(mine)
    engine._drop(theirs)

    from agent_runtime.builds import sweep
    from agent_runtime import serve_registry

    rows = [{"work_id": "build:detected:1", "kind": "build", "workspace_id": first.id, "outcome": None}]
    monkeypatch.setattr(sweep, "build_rows", lambda _now: rows)
    assert triggers.try_rekey(realm.id).busy is RekeyBusy.BUILD
    rows[0]["workspace_id"] = neighbour.id
    assert triggers.busy_fact(read_rekey_journal(realm.id)["map"]) is None

    import os

    serves = [{"pid": os.getpid(), "classification": serve_registry.CLASSIFICATION_LIVE}]
    monkeypatch.setattr(serve_registry, "list_serve_instances", lambda _root, **_k: serves)
    assert triggers.busy_fact(read_rekey_journal(realm.id)["map"]) is None  # this process is the serve
    serves.append({"pid": os.getpid() + 1, "classification": serve_registry.CLASSIFICATION_UNKNOWN})
    attempt = triggers.try_rekey(realm.id)
    assert attempt.busy is RekeyBusy.SERVE
    assert attempt.refusal_details() == {"realm_id": realm.id, "running": "serve", "retry_after_ms": 5000}
    serves.pop()

    held, release = threading.Event(), threading.Event()

    def _restore() -> None:  # an operator checkpoint restore: holds the workspace-writer lock from its thread
        with workdir._WORKDIR_LOCK:
            held.set()
            release.wait(10)

    writer = threading.Thread(target=_restore)
    writer.start()
    assert held.wait(10)
    try:
        assert triggers.try_rekey(realm.id).busy is RekeyBusy.TURN
    finally:
        release.set()
        writer.join(10)
    assert _state(realm.id) == RekeyState.OWED.value  # nothing above moved anything

    [done] = triggers.run_owed_rekeys(RekeyTrigger.IDLE)
    assert done.done and done.busy is None and triggers.pending_rekeys() == []
    assert RealmStore().get(done.journal["map"]["realm_new"]).name == "Team"
    assert triggers.run_owed_rekeys(RekeyTrigger.IDLE) == []


def test_a_rename_the_os_refuses_names_its_step_and_the_next_trigger_finishes(tmp_path, monkeypatch):
    """Mutations: let the ``OSError`` escape ``try_rekey`` -> ``run_owed_rekeys`` reports nothing, red; drop the
    ``blocked`` write in ``rekey_realm`` -> no step is named, red; clear ``blocked`` never -> the done journal
    still names a blocked step, red."""
    realm, _first, _second, _extra, _head = _left_realm(tmp_path)
    owe_rekey(realm.id, reason="membership_left")
    real = Path.rename

    def refused(self, target):
        if "boards" in self.parts:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", refused)
    [attempt] = triggers.run_owed_rekeys(RekeyTrigger.IDLE)
    assert attempt.busy is RekeyBusy.RENAME_BLOCKED and not attempt.done
    assert attempt.journal["state"] == RekeyState.RUNNING.value
    assert attempt.journal["blocked"] == {"step": "rename", "error": "PermissionError"}
    assert attempt.refusal_details() == {
        "realm_id": realm.id, "running": "rename_blocked", "retry_after_ms": 15000, "blocked_step": "rename"}
    with pytest.raises(RealmSyncError) as refusal:
        triggers.finish_rekey_or_refuse(realm.id)
    assert (refusal.value.code, refusal.value.retryable) == ("realm_busy", True)
    assert refusal.value.safe_details["running"] == "rename_blocked"

    monkeypatch.setattr(Path, "rename", real)
    journal = triggers.finish_rekey_or_refuse(realm.id)
    assert (journal["state"], journal["blocked"], journal["leftover"]) == (RekeyState.DONE.value, None, [])
    assert triggers.finish_rekey_or_refuse(realm.id) == journal  # done: answered, not run again
    assert triggers.finish_rekey_or_refuse("realm_never_left") is None


def test_a_lens_database_held_by_its_poller_holds_the_rekey_and_no_watch_keeps_the_old_workspace(tmp_path, monkeypatch):
    """Mutation: swallow every ``sqlite3.Error`` in ``_rekey_lens`` again -> the re-key turns ``done`` with the
    watch still on the old workspace id, red."""
    import sqlite3

    from agent_runtime import realm_rekey_outside
    from agent_runtime.lens.store import LensStore, default_path
    from tests.agent_runtime.lens.test_lens_contracts import _manifest

    realm, first, _second, _extra, _head = _left_realm(tmp_path)
    LensStore().create(_manifest(), workspace_id=first.id)
    owed = owe_rekey(realm.id, reason="membership_left")
    monkeypatch.setattr(realm_rekey_outside, "LENS_WAIT_SECONDS", 0.2)
    poller = sqlite3.connect(default_path(), isolation_level=None)
    poller.execute("BEGIN EXCLUSIVE")
    try:
        attempt = triggers.try_rekey(realm.id)
    finally:
        poller.execute("ROLLBACK")
        poller.close()
    assert attempt.busy is RekeyBusy.RENAME_BLOCKED and attempt.journal["blocked"] == {"step": "outside", "error": "PermissionError"}
    assert triggers.try_rekey(realm.id).done
    assert [row["workspace_id"] for row in LensStore().monitors()] == [owed["map"]["workspaces"][first.id]]


def test_an_agent_with_a_live_run_holds_the_rekey_as_a_turn(tmp_path, monkeypatch):
    """Mutation: raise the untyped ``RuntimeError`` in ``step_agents`` again -> it escapes ``try_rekey``, red."""
    from agent_runtime.persona_assignments import PersonaInstanceStore

    realm, _first, _second, _extra, _head = _left_realm(tmp_path)
    owe_rekey(realm.id, reason="membership_left")
    monkeypatch.setattr(PersonaInstanceStore, "_has_live_binding", lambda self, instance: instance.id == HELPER)
    attempt = triggers.try_rekey(realm.id)
    assert attempt.busy is RekeyBusy.TURN and attempt.journal["blocked"] == {"step": "agents", "error": "RekeyAgentBusy"}
    monkeypatch.undo()
    assert triggers.try_rekey(realm.id).done


def test_a_serve_start_runs_the_owed_rekey_before_anything_reads_the_store(tmp_path, monkeypatch):
    """Mutation: drop the ``run_owed_rekeys`` call from ``BootPhases._run_boot_sweeps`` -> the realm still
    holds its old id after the boot sweeps, red."""
    from agent_runtime.builds import sweep
    from hermes_cli.harness_parts.serve.boot_phases import BootPhases

    realm, _first, _second, _extra, _head = _left_realm(tmp_path)
    owed = owe_rekey(realm.id, reason="membership_left")
    monkeypatch.setattr(sweep, "boot_builds", lambda: None)
    marks: list[str] = []

    BootPhases._run_boot_sweeps(types.SimpleNamespace(timeline=types.SimpleNamespace(mark=marks.append)))

    assert _state(realm.id) == RekeyState.DONE.value
    held = {item.id for item in RealmStore().list_all(include_archived=True)}
    assert owed["map"]["realm_new"] in held and realm.id not in held
    assert marks.index("project_migration_ms") < marks.index("realm_rekey_ms")


def test_the_serve_runs_it_when_its_last_turn_ends_and_on_its_tick(tmp_path):
    """Mutations: drop ``register_turn_idle_listener`` -> nothing runs when the turn ends (the tick is an hour
    away), red; drop the ``_loop`` body's ``_run_idle`` -> the second realm is never re-keyed, red."""
    realm, _first, _second, _extra, _head = _left_realm(tmp_path)
    owe_rekey(realm.id, reason="membership_left")
    stop = threading.Event()
    try:
        triggers.start_rekey_ticker(stop_event=stop, interval_s=3600.0)
        with turn_activity.admitted_turn("turn_1"):
            time.sleep(0.2)
            assert _state(realm.id) == RekeyState.OWED.value
        _wait_done(realm.id)
    finally:
        stop.set()
        turn_activity._IDLE_LISTENERS.discard(triggers._on_turn_idle)

    other = RealmStore().create(name="Other", server_id="srv_other", realm_id="realm_other")
    WorkspaceStore().create(name="Theirs", realm_id=other.id)
    owe_rekey(other.id, reason="membership_left")
    stop = threading.Event()
    try:
        triggers.start_rekey_ticker(stop_event=stop, interval_s=0.05)
        _wait_done(other.id)
    finally:
        stop.set()
        turn_activity._IDLE_LISTENERS.discard(triggers._on_turn_idle)


def _wait_done(realm_id: str) -> None:
    deadline = time.monotonic() + 15
    while _state(realm_id) != RekeyState.DONE.value:
        assert time.monotonic() < deadline, f"{realm_id} was not re-keyed: {read_rekey_journal(realm_id)}"
        time.sleep(0.05)
