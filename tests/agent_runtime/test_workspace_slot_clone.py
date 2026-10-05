"""Clone a slot and run a recipe step, Phase B (plan ``build-running-work-2026-10-04.md`` §3.5, row H11).

Both spawn through the process registry as background terminal rows (a fake registry here).
Clone authenticates with the machine's own git: the spawned argv and env carry NO credential —
hermes hands git exactly ``GIT_TERMINAL_PROMPT=0``. Success binds and re-reports; an auth
failure ends ``clone_auth_required`` with redacted stderr; a command step runs ONLY on an
explicit ``run_step``, never after a clone on its own.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import types
from argparse import Namespace

import pytest

from agent_runtime import serve_rpc, workspace_slot_setup
from agent_runtime.machine_roots import load_machine_roots, machine_roots_cache_clear, write_machine_roots
from agent_runtime.redaction import is_credential_key
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slot_recipe import text_carries_credential
from agent_runtime.workspace_slot_runs import all_runs, runs_path
from agent_runtime.workspace_slot_setup import clone_slot, run_step, settle_runs
from agent_runtime.workspace_slots import SlotRefused, load_document, write_document

CLONE_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"
ISSUED = "2026-10-05T12:00:00+00:00"
LATER = "2026-10-05T13:00:00+00:00"
LATEST = "2026-10-05T14:00:00+00:00"
FILL_VALUE = "C:\\fill\\flutter-root-VALUE-41"


class _Registry:
    """The registry's two doors the setup verbs use: ``spawn_local`` and ``get``."""

    def __init__(self):
        self.spawned, self.sessions = [], {}

    def spawn_local(self, command, **kwargs):
        sid = f"proc_{len(self.spawned) + 1:04d}"
        self.spawned.append((command, kwargs))
        self.sessions[sid] = types.SimpleNamespace(id=sid, exited=False, exit_code=None, output_buffer="",
                                                   completion_reason="exited")
        return self.sessions[sid]

    def get(self, sid):
        return self.sessions.get(sid)

    def finish(self, sid, code, output=""):
        session = self.sessions[sid]
        session.exited, session.exit_code, session.output_buffer = True, code, output


def call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _decl(name="launcher", url=CLONE_URL) -> dict:
    return {"name": name, "repo": {"clone_url": url, "default_branch": "main"},
            "toolchain": {"tools": [{"name": "flutter"}], "env_keys": [{"key": "FLUTTER_ROOT", "required": True}]}}


@pytest.fixture
def workspace():
    machine_roots_cache_clear()
    workspace_id = WorkspaceStore().create(name="Clone").id
    reply = call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": [_decl(), _decl("backend")],
                                                      "issued_at": ISSUED})
    assert "result" in reply, reply
    return workspace_id


@pytest.fixture
def registry():
    return _Registry()


def _cloned(dest, url=CLONE_URL):
    """What a successful ``git clone`` leaves behind: a checkout whose origin is the URL."""

    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "remote", "add", "origin", url], check=True)


# ── no credential, anywhere ──────────────────────────────────────────────────


def test_the_clone_spawns_the_machines_git_with_no_credential(workspace, registry, tmp_path, monkeypatch):
    from agent_runtime.realm_membership import RealmSyncCredential

    # The realm's brokered credential seam is NOT the clone's: reaching it reds this test.
    monkeypatch.setattr(RealmSyncCredential, "git_extra_config", lambda self: pytest.fail("realm credential reused"))
    dest = tmp_path / "work" / "launcher"
    reply = clone_slot(workspace, "launcher", str(dest), issued_at=ISSUED, registry=registry, watch=False)
    (command, kwargs), = registry.spawned
    assert shlex.split(command) == ["git", "clone", "--branch", "main", "--", CLONE_URL, str(dest)] == reply["argv"]
    assert kwargs["env_vars"] == {"GIT_TERMINAL_PROMPT": "0"} and kwargs["persist_on_release"] is True
    assert not any(text_carries_credential(token) for token in shlex.split(command))
    assert not any(is_credential_key(key) or text_carries_credential(value) for key, value in kwargs["env_vars"].items())
    run = reply["run"]
    assert run["work_id"] == f"terminal:{run['run_id']}" and run["status"] == "running"
    assert set(run) >= {"workspace_id", "slot", "step_id", "dest_path", "issued_at"} and "env" not in run and "argv" not in run


def test_a_clone_url_with_userinfo_never_enters_a_record_or_a_spawn(workspace, registry, tmp_path):
    token_url = "https://not-a-real-token@github.com/ArcadiaLabsLLC/EterniaLauncher.git"
    refused = call("runtime.workspace.slots.declare", {"workspace_id": workspace, "slots": [_decl(url=token_url)],
                                                        "issued_at": LATER})
    assert refused["error"]["data"]["reason"] == "clone_url_carries_credential"
    # A peer's document is not validated on pull: the clone door refuses it on its own.
    document = load_document(workspace)
    document["slots"]["launcher"]["repo"]["clone_url"] = token_url
    write_document(workspace, document)
    with pytest.raises(SlotRefused) as caught:
        clone_slot(workspace, "launcher", str(tmp_path / "x"), issued_at=ISSUED, registry=registry, watch=False)
    assert caught.value.reason == "clone_url_carries_credential" and registry.spawned == []


# ── success binds; failures are typed and redacted ───────────────────────────


def test_a_clone_that_exits_zero_binds_the_slot_and_reports(workspace, registry, tmp_path):
    dest = tmp_path / "work" / "launcher"
    run = clone_slot(workspace, "launcher", str(dest), issued_at=ISSUED, registry=registry, watch=False)["run"]
    _cloned(dest)
    registry.finish(run["run_id"], 0, "Cloning into 'launcher'...\n")
    settled, = settle_runs(workspace, registry)
    assert settled["status"] == "succeeded" and settled["exit_code"] == 0
    assert load_machine_roots(refresh=True).roots["launcher"] == str(dest)
    me = next(iter(load_document(workspace)["machines"].values()))
    assert me["slots"]["launcher"]["checkout"] == "matches"
    # Call 8d: nothing ran after the clone on its own — the clone is the only spawn.
    assert len(registry.spawned) == 1


@pytest.mark.parametrize(("stderr", "reason"), [
    ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", "clone_auth_required"),
    ("git@github.com: Permission denied (publickey).", "clone_auth_required"),
    ("remote: Repository not found.\nfatal: repository 'https://github.com/x/y.git/' not found", "clone_repository_not_found"),
    ("fatal: unable to access 'https://github.com/x/': Could not resolve host: github.com", "clone_failed"),
])
def test_a_failed_clone_ends_typed_and_unbound(workspace, registry, tmp_path, stderr, reason):
    run = clone_slot(workspace, "launcher", str(tmp_path / "l"), issued_at=ISSUED, registry=registry, watch=False)["run"]
    registry.finish(run["run_id"], 128, "Cloning into 'l'...\n" + stderr)
    settled, = settle_runs(workspace, registry)
    assert (settled["status"], settled["reason"], settled["exit_code"]) == ("failed", reason, 128)
    assert "launcher" not in load_machine_roots(refresh=True).roots


def test_auth_failure_evidence_is_redacted(workspace, registry, tmp_path):
    run = clone_slot(workspace, "launcher", str(tmp_path / "l"), issued_at=ISSUED, registry=registry, watch=False)["run"]
    leak = "fatal: Authentication failed for 'https://someone:not-a-real-password-77@github.com/x/y.git/'"
    registry.finish(run["run_id"], 128, leak + "\nAuthorization: Bearer not-a-real-bearer-88\n")
    settled, = settle_runs(workspace, registry)
    assert settled["reason"] == "clone_auth_required" and "Authentication failed" in settled["evidence"]
    stored = runs_path().read_text(encoding="utf-8")
    for secret in ("not-a-real-password-77", "not-a-real-bearer-88"):
        assert secret not in settled["evidence"] and secret not in stored


def test_a_run_the_registry_forgot_reads_lost(workspace, registry, tmp_path):
    run = clone_slot(workspace, "launcher", str(tmp_path / "l"), issued_at=ISSUED, registry=registry, watch=False)["run"]
    registry.sessions.pop(run["run_id"])
    assert settle_runs(workspace, registry)[0]["status"] == "lost"
    # Positive control: a run still running stays running.
    other = clone_slot(workspace, "backend", str(tmp_path / "b"), issued_at=ISSUED, registry=registry, watch=False)["run"]
    assert settle_runs(workspace, registry)[0]["run_id"] == other["run_id"]
    assert next(r for r in all_runs() if r["run_id"] == other["run_id"])["status"] == "running"


# ── refusals and the replay guard ────────────────────────────────────────────


def test_clone_refusals_are_typed(workspace, registry, tmp_path):
    def refused(slot, dest, issued_at=ISSUED):
        with pytest.raises(SlotRefused) as caught:
            clone_slot(workspace, slot, dest, issued_at=issued_at, registry=registry, watch=False)
        return caught.value.reason

    full = tmp_path / "full"
    full.mkdir()
    (full / "file.txt").write_text("x", encoding="utf-8")
    assert refused("launcher", str(full)) == "dest_not_empty"
    assert refused("launcher", "relative/path") == "invalid_path"
    assert refused("nowhere", str(tmp_path / "n")) == "slot_not_declared"
    bound = tmp_path / "bound"
    bound.mkdir()
    write_machine_roots({"launcher": str(bound)}, dry_run=False)
    assert refused("launcher", str(tmp_path / "x")) == "slot_already_bound"
    assert registry.spawned == []


def test_a_replayed_or_concurrent_clone_is_refused(workspace, registry, tmp_path):
    dest = str(tmp_path / "l")
    run = clone_slot(workspace, "launcher", dest, issued_at=ISSUED, registry=registry, watch=False)["run"]
    with pytest.raises(SlotRefused) as running:
        clone_slot(workspace, "launcher", dest, issued_at=LATER, registry=registry, watch=False)
    assert running.value.reason == "step_running"
    registry.finish(run["run_id"], 128, "fatal: Authentication failed")
    settle_runs(workspace, registry)
    with pytest.raises(SlotRefused) as replayed:
        clone_slot(workspace, "launcher", dest, issued_at=ISSUED, registry=registry, watch=False)
    assert replayed.value.reason == "stale_request"
    # Positive control: "sign in, then Clone again" — a NEWER request spawns.
    clone_slot(workspace, "launcher", dest, issued_at=LATER, registry=registry, watch=False)
    assert len(registry.spawned) == 2


# ── run_step: an owner command, on an explicit request, under the slot env ───


@pytest.fixture
def bound_launcher(workspace, tmp_path):
    checkout = tmp_path / "checkouts" / "launcher"
    _cloned(checkout)
    call("runtime.workspace.slot.bind", {"workspace_id": workspace, "slot": "launcher", "path": str(checkout),
                                         "issued_at": ISSUED})
    tool = str(tmp_path / "sdk" / "flutter.bat")
    call("runtime.workspace.slot.env.set", {"workspace_id": workspace, "slot": "launcher", "issued_at": ISSUED,
                                            "env": {"FLUTTER_ROOT": FILL_VALUE}, "tool_paths": {"flutter": tool},
                                            "path_prepend": [str(tmp_path / "sdk")]})
    steps = [{"id": "pub_get", "kind": "command", "argv": ["flutter", "pub", "get"]},
             {"id": "seed", "kind": "command", "argv": ["python", "seed.py"], "cwd_slot": "backend", "run": "never_auto"}]
    assert "result" in call("runtime.workspace.recipe.set", {"workspace_id": workspace, "slot": "launcher",
                                                             "steps": steps, "revision": 0, "issued_at": ISSUED})
    return checkout, tool


def test_run_step_spawns_under_the_slot_env_and_resolves_the_tool(workspace, registry, bound_launcher, tmp_path):
    checkout, tool = bound_launcher
    reply = run_step(workspace, "launcher", "pub_get", issued_at=LATER, registry=registry, watch=False)
    (command, kwargs), = registry.spawned
    assert shlex.split(command) == [tool, "pub", "get"] and kwargs["cwd"] == str(checkout)
    assert kwargs["env_vars"]["FLUTTER_ROOT"] == FILL_VALUE
    assert kwargs["env_vars"]["PATH"].split(os.pathsep)[0] == str(tmp_path / "sdk")
    assert reply["env_source"] == "slot:launcher" and reply["run"]["status"] == "running"
    # The run record carries no environment value.
    assert FILL_VALUE not in runs_path().read_text(encoding="utf-8")
    registry.finish(reply["run"]["run_id"], 1, "pub get failed")
    assert settle_runs(workspace, registry)[0]["reason"] == "command_failed"


def test_run_step_refusals_are_typed(workspace, registry, bound_launcher):
    def refused(step_id):
        with pytest.raises(SlotRefused) as caught:
            run_step(workspace, "launcher", step_id, issued_at=LATER, registry=registry, watch=False)
        return caught.value.reason

    assert refused("tool:flutter") == "step_not_runnable"
    assert refused("clone") == "step_not_runnable"
    assert refused("nope") == "unknown_step"
    assert refused("seed") == "slot_unbound_here"  # its cwd_slot (backend) is not bound here
    assert registry.spawned == []


# ── the doors ────────────────────────────────────────────────────────────────


def test_the_rpc_doors_spawn_and_show_settles_the_run(workspace, registry, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_slot_setup, "spawning_registry", lambda: registry)
    monkeypatch.setattr(workspace_slot_setup, "watch_run", lambda *a, **k: None)
    dest = tmp_path / "work" / "launcher"
    reply = call("runtime.workspace.slot.clone", {"workspace_id": workspace, "slot": "launcher",
                                                  "dest_path": str(dest), "issued_at": ISSUED})["result"]
    _cloned(dest)
    registry.finish(reply["run"]["run_id"], 0)
    shown = call("runtime.workspace.recipe.show", {"workspace_id": workspace})["result"]["slots"]["launcher"]
    assert shown["runs"]["clone"]["status"] == "succeeded" and shown["checklist"] != "not_cloned"
    again = call("runtime.workspace.slot.clone", {"workspace_id": workspace, "slot": "launcher",
                                                  "dest_path": str(tmp_path / "y"), "issued_at": LATEST})
    assert again["error"]["code"] == serve_rpc.ERR_CONFLICT and again["error"]["data"]["reason"] == "slot_already_bound"
    step = call("runtime.workspace.recipe.run_step", {"workspace_id": workspace, "slot": "launcher", "step_id": "clone",
                                                      "issued_at": LATEST})
    assert step["error"]["data"]["reason"] == "step_not_runnable"


def test_the_cli_clone_waits_for_the_run_and_binds(workspace, registry, tmp_path, monkeypatch, capsys):
    from hermes_cli.harness_parts import workspace_slots_commands

    dest = tmp_path / "cli" / "launcher"

    class _Finishing(_Registry):
        def spawn_local(self, command, **kwargs):
            session = super().spawn_local(command, **kwargs)
            _cloned(dest)
            self.finish(session.id, 0)
            return session

    finishing = _Finishing()
    monkeypatch.setattr(workspace_slot_setup, "spawning_registry", lambda: finishing)
    args = Namespace(workspace_id=workspace, slot="launcher", dest_path=str(dest), issued_at=ISSUED, json=True,
                     output="json")
    assert workspace_slots_commands._cmd_workspace_slots_clone(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert json.dumps(printed).count('"succeeded"') >= 1
    assert load_machine_roots(refresh=True).roots["launcher"] == str(dest)


def test_the_runs_file_never_travels_with_the_realm():
    from agent_runtime.realm_sync.families import _is_hard_excluded_path
    from agent_runtime.workspace_slot_runs import MACHINE_SLOT_RUNS_FILENAME

    assert _is_hard_excluded_path(MACHINE_SLOT_RUNS_FILENAME)
    assert not _is_hard_excluded_path("store/workspace_slots/ws.json")  # positive control: the document travels
