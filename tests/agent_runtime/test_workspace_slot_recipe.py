"""The slot setup recipe, read from the repository (plan ``slot-setup-recipe-2026-11-15.md`` §2–§5).

A recipe is ``.eternia/setup/recipe.json`` in the slot's checkout, read by one function per
platform; it is blank by default, never decides Ready, and hermes never writes it. ``ready`` is
the checkout alone and ``unknown`` whenever the checkout is unknown, never optimistically ``yes``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from agent_runtime import serve_rpc
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slot_recipe import readiness
from agent_runtime.workspace_slot_repo_recipe import read_recipe
from agent_runtime.workspace_slots import declare, load_document, write_document
from agent_runtime.workspace_slots_sync import merge_documents

CLONE_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"
ISSUED = "2026-10-05T12:00:00+00:00"
LATER = "2026-10-05T13:00:00+00:00"
REMOVED = "2026-10-05T14:00:00+00:00"
ROOT = Path(__file__).resolve().parents[2]

RECIPE = {
    "version": 1,
    "env_keys": [{"key": "SLOT_RECIPE_TEST_KEY", "secret": True, "hint": "Ask the team", "url": "https://docs.example.com"}],
    "dotenv": {"path": ".env", "example": ".env.example", "keys": [{"key": "API_BASE"}]},
    "platforms": {p: {"script": "setup.sh", "tools": [{"name": "definitely_absent_tool_zz", "min_version": "3.4"}]}
                  for p in ("windows", "macos", "linux")},
}


def call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _decl(name="launcher") -> dict:
    return {"name": name, "repo": {"clone_url": CLONE_URL, "default_branch": "main"}, "toolchain": {"kind": "flutter"}}


def write_recipe(repo: Path, recipe=RECIPE, script: str | None = "echo set up\n") -> None:
    setup = repo / ".eternia" / "setup"
    setup.mkdir(parents=True, exist_ok=True)
    (setup / "recipe.json").write_text(recipe if isinstance(recipe, str) else json.dumps(recipe), encoding="utf-8")
    if script is not None:
        (setup / "setup.sh").write_text(script, encoding="utf-8")


def _checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", CLONE_URL], check=True)
    return path


@pytest.fixture
def workspace():
    machine_roots_cache_clear()
    workspace_id = WorkspaceStore().create(name="Recipe").id
    reply = call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": [_decl(), _decl("backend")],
                                                      "issued_at": ISSUED})
    assert "result" in reply, reply
    return workspace_id


@pytest.fixture
def bound(workspace, tmp_path):
    repo = _checkout(tmp_path / "launcher")
    call("runtime.workspace.slot.bind", {"workspace_id": workspace, "slot": "launcher", "path": str(repo),
                                         "issued_at": ISSUED})
    return repo


def _show(workspace) -> dict:
    return call("runtime.workspace.recipe.show", {"workspace_id": workspace})["result"]["slots"]


# ── a recipe never changes Ready ─────────────────────────────────────────────


@pytest.mark.parametrize("recipe", [None, RECIPE, "{not json"])
def test_a_recipe_never_changes_ready(workspace, bound, recipe):
    """Ready is the checkout alone, recipe present (every item to do), absent or unreadable (§5 row 1).
    Killing mutation: ``_slot_checklist`` answering ``ready: no`` while the recipe has items ``left`` -> red."""

    if recipe is not None:
        write_recipe(bound, recipe)
    shown = _show(workspace)["launcher"]
    assert (shown["ready"], shown["checklist"], shown["blocking"]) == ("yes", "ready", [])
    assert [step["id"] for step in shown["steps"]] == ["clone"]
    if recipe is RECIPE:
        assert shown["recipe"]["left"] >= 2  # positive control: there IS something left to do here


# ── blank by default ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(("setup", "blank", "why"), [
    ("absent", "no_recipe", "no_recipe"),
    ("v2", "unreadable", "unsupported_version"),
    ("large", "unreadable", "too_large"),
    ("not_json", "unreadable", "not_json"),
    ("extra_field", "unreadable", "invalid_shape"),
    ("credential_hint", "unreadable", "credential_in_step"),
    ("credential_url", "unreadable", "credential_in_step"),
])
def test_no_recipe_reads_blank(tmp_path, setup, blank, why):
    """§5 row 2. Killing mutation: derive tool items from ``toolchain.kind`` when the file is missing -> red."""

    repo = tmp_path / "repo"
    repo.mkdir()
    bodies = {
        "v2": {**RECIPE, "version": 2},
        "large": {**RECIPE, "env_keys": [{"key": "K", "hint": "x" * (65 * 1024)}]},
        "not_json": "{",
        "extra_field": {**RECIPE, "steps": []},
        "credential_hint": {**RECIPE, "env_keys": [{"key": "K", "hint": "Authorization: Bearer not-a-real-bearer-0123"}]},
        "credential_url": {**RECIPE, "env_keys": [{"key": "K", "url": "https://user:not-a-real-pass@example.com/x"}]},
    }
    if setup != "absent":
        write_recipe(repo, bodies[setup])
    read = read_recipe(repo, "linux")
    assert (read.recipe, read.blank, read.why) == (None, blank, why)
    # Positive control: the well-formed recipe in the same folder reads.
    write_recipe(repo)
    assert read_recipe(repo, "linux").recipe is not None


def test_an_unbound_slot_and_a_checkout_without_the_folder_show_a_blank_setup(workspace, bound):
    shown = _show(workspace)
    assert shown["backend"]["recipe"] == {"platform": shown["backend"]["recipe"]["platform"], "blank": "not_cloned",
                                          "why": "not_cloned"}
    assert shown["launcher"]["recipe"]["blank"] == "no_recipe" and "items" not in shown["launcher"]["recipe"]
    write_recipe(bound)
    assert [i["id"] for i in _show(workspace)["launcher"]["recipe"]["items"]] == \
        ["tool:definitely_absent_tool_zz", "env_key:SLOT_RECIPE_TEST_KEY", "dotenv"]


# ── a computer sees only its platform ────────────────────────────────────────


def test_a_computer_sees_only_its_own_platform(tmp_path):
    """§5 row 3. Killing mutation: fall back to the first listed platform in ``parse_recipe`` -> red."""

    repo = tmp_path / "repo"
    repo.mkdir()
    write_recipe(repo, {**RECIPE, "platforms": {"linux": RECIPE["platforms"]["linux"]}})
    windows = read_recipe(repo, "windows")
    assert windows.recipe is None and windows.blank == "no_recipe"
    assert windows.secret_keys == frozenset() and windows.keys == frozenset()  # keys included
    linux = read_recipe(repo, "linux")
    assert linux.secret_keys == {"SLOT_RECIPE_TEST_KEY"} and linux.recipe.script == "setup.sh"


# ── a script outside the folder is refused ───────────────────────────────────


@pytest.mark.parametrize("script", ["../x.sh", "sub/x.sh", "/etc/passwd", "..\\x.ps1"])
def test_a_script_outside_the_setup_folder_is_refused(tmp_path, script):
    """§5 row 4. Killing mutation: accept any ``script`` string in ``_script`` -> red."""

    repo = tmp_path / "repo"
    (repo / ".eternia" / "setup" / "sub").mkdir(parents=True)
    (repo / ".eternia" / "setup" / "sub" / "x.sh").write_text("true\n", encoding="utf-8")
    (repo / ".eternia" / "x.sh").write_text("true\n", encoding="utf-8")
    write_recipe(repo, {**RECIPE, "platforms": {"linux": {"script": script}}}, script=None)
    assert (read_recipe(repo, "linux").blank, read_recipe(repo, "linux").why) == ("unreadable", "script_outside_setup")


def test_a_script_symlinked_out_of_the_folder_is_refused(tmp_path):
    """Killing mutation: drop the resolved-path containment check in ``read_recipe`` -> red."""

    repo = tmp_path / "repo"
    write_recipe(repo, script=None)
    outside = tmp_path / "outside.sh"
    outside.write_text("rm -rf ~\n", encoding="utf-8")
    (repo / ".eternia" / "setup" / "setup.sh").symlink_to(outside)
    assert read_recipe(repo, "linux").why == "script_outside_setup"


# ── the doors ────────────────────────────────────────────────────────────────


def test_recipe_script_shows_the_text_and_its_hash(workspace, bound):
    write_recipe(bound, script="echo 'install the tools'\n")
    subprocess.run(["git", "-C", str(bound), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q",
                    "--allow-empty", "-m", "base"], check=True)
    shown = call("runtime.workspace.recipe.script", {"workspace_id": workspace, "slot": "launcher"})["result"]
    assert shown["text"] == "echo 'install the tools'\n" and shown["path"] == ".eternia/setup/setup.sh"
    assert shown["sha256"] == hashlib.sha256(b"echo 'install the tools'\n").hexdigest() and len(shown["commit"]) == 40
    script = _show(workspace)["launcher"]["recipe"]["script"]
    assert (script["id"], script["sha256"], script["last_run"]) == ("script", shown["sha256"], None)
    blank = call("runtime.workspace.recipe.script", {"workspace_id": workspace, "slot": "backend"})
    assert blank["error"]["data"]["reason"] == "recipe_blank"


def test_recipe_set_is_refused_the_recipe_lives_in_the_repository(workspace):
    reply = call("runtime.workspace.recipe.set", {"workspace_id": workspace, "slot": "launcher", "steps": [],
                                                  "revision": 0, "issued_at": LATER})
    assert reply["error"]["data"]["reason"] == "recipe_in_repository"
    assert "recipe" not in load_document(workspace)["slots"]["launcher"]


# ── the slot record's revision (read old, write new) ─────────────────────────


def test_a_changed_declaration_and_a_removal_advance_the_slot_revision(workspace):
    slots = load_document(workspace)["slots"]
    assert slots["launcher"]["revision"] == 0 and "recipe" not in slots["launcher"]
    declare(workspace, [{**_decl(), "context": {"role": "frontend"}}], issued_at=LATER, machine="m1")
    slots = load_document(workspace)["slots"]
    assert slots["launcher"]["revision"] == 1 and slots["backend"]["revision"] == 1  # changed; removed
    assert slots["backend"]["removed_at"] == LATER


def test_an_older_writers_recipe_revision_is_read_and_the_next_write_drops_it(workspace):
    document = load_document(workspace)
    launcher = document["slots"]["launcher"]
    del launcher["revision"]
    launcher["recipe"] = {"revision": 4, "steps": [{"id": "x", "kind": "command", "argv": ["x"]}]}
    write_document(workspace, document)
    declare(workspace, [_decl(), _decl("backend")], issued_at=LATER, machine="m1")
    held = load_document(workspace)["slots"]["launcher"]
    assert held["revision"] == 4 and "recipe" not in held


def test_a_peer_removal_beats_an_older_declaration_in_the_realm_merge(workspace):
    """A removal advances the revision like a re-declaration, so the NEWER decision wins the merge."""

    before = load_document(workspace)
    declare(workspace, [{**_decl(), "context": {"role": "edited"}}, _decl("backend")], issued_at=LATER, machine="m1")
    mine = load_document(workspace)
    write_document(workspace, before)
    declare(workspace, [_decl("backend")], issued_at=REMOVED, machine="mach_peer")
    theirs = load_document(workspace)
    assert theirs["slots"]["launcher"]["revision"] == mine["slots"]["launcher"]["revision"] == 1
    assert merge_documents(mine, theirs)["slots"]["launcher"]["removed_at"] == REMOVED


# ── the old shape has one fate ───────────────────────────────────────────────

_OLD_KEYS = {"toolchain": {"tools", "env_keys", "dotenv"}, "recipe": {"steps"}}


def _old_shape_reads(tree: ast.AST) -> list[str]:
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            receiver, key = node.value, node.slice.value
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
              and node.args and isinstance(node.args[0], ast.Constant)):
            receiver, key = node.func.value, node.args[0].value
        else:
            continue
        source = ast.unparse(receiver)
        if any(owner in source and key in keys for owner, keys in _OLD_KEYS.items()):
            hits.append(f"{node.lineno}: {ast.unparse(node)}")
    return hits


def test_the_old_in_declaration_recipe_is_read_nowhere():
    """§5's last row: ``toolchain.tools`` / ``env_keys`` / ``dotenv`` and ``recipe.steps`` are read by no fork
    module. Killing mutation: read ``toolchain.get("tools")`` in the probe -> red, naming the line."""

    files = [*sorted((ROOT / "agent_runtime").rglob("*.py")), *sorted((ROOT / "hermes_cli" / "harness_parts").rglob("*.py"))]
    found = {str(path.relative_to(ROOT)): hits for path in files
             if (hits := _old_shape_reads(ast.parse(path.read_text(encoding="utf-8"))))}
    assert found == {}
    # Positive control: the walk sees the shape it forbids.
    assert _old_shape_reads(ast.parse('(slot.get("toolchain") or {}).get("tools")'))


# ── readiness: the truth table ───────────────────────────────────────────────


@pytest.mark.parametrize(("row", "ready", "checklist"), [
    ({"bound": True, "checkout": "matches"}, "yes", "ready"),
    (None, "unknown", "unknown"),
    ({"bound": False, "status": "not_cloned"}, "no", "not_cloned"),
    ({"bound": True, "status": "path_missing"}, "no", "path_missing"),
    ({"bound": True, "checkout": "remote_mismatch"}, "no", "remote_mismatch"),
    ({"bound": True, "checkout": "not_a_repo"}, "no", "needs_setup"),
    ({"bound": True, "checkout": "unknown"}, "unknown", "unknown"),
    ({"bound": True}, "unknown", "unknown"),
    # An older peer's row with tool and key state: still the checkout alone.
    ({"bound": True, "checkout": "matches", "tools": {"flutter": {"status": "missing", "version": None}},
      "env_keys": {"FLUTTER_ROOT": "missing"}}, "yes", "ready"),
])
def test_ready_truth_table(row, ready, checklist):
    answer = readiness("launcher", _decl(), row)
    assert (answer["ready"], answer["checklist"]) == (ready, checklist)
    assert answer["blocking"] == ([] if ready != "no" else ["clone"])


def test_a_never_reported_machine_reads_unknown_not_ready(workspace):
    checklist = _show(workspace)["launcher"]
    assert checklist["ready"] == "unknown" and checklist["unknown"] == ["clone"]
    assert checklist["steps"][0]["why"] == "not_reported"


def test_the_report_status_is_the_readiness_answer(tmp_path):
    machine_roots_cache_clear()
    workspace_id = WorkspaceStore().create(name="Probe").id
    bare = {"name": "launcher", "repo": {"clone_url": CLONE_URL}}
    call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": [bare], "issued_at": ISSUED})
    repo = tmp_path / "launcher"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://example.com/fork.git"], check=True)
    row = call("runtime.workspace.slot.bind", {"workspace_id": workspace_id, "slot": "launcher", "path": str(repo),
                                               "issued_at": ISSUED})["result"]["report"]
    assert row["checkout"] == "remote_mismatch" and row["status"] == "needs_setup"
    shown = _show(workspace_id)["launcher"]
    assert shown["ready"] == "no" and shown["checklist"] == "remote_mismatch"
    # Positive control: the declared remote makes the same checkout ready.
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", CLONE_URL], check=True)
    again = call("runtime.workspace.slots.report", {"workspace_id": workspace_id})["result"]["slots"]["launcher"]
    assert again["status"] == "ready" and _show(workspace_id)["launcher"]["ready"] == "yes"


def test_a_bound_local_folder_reports_its_real_readiness_and_offers_only_locate(tmp_path):
    """RT-PROJECT-LOCAL-FOLDER-READINESS. Mutations: probe ``.git`` before ``repo.local`` in
    ``_SlotProbe.checkout`` -> ``not_a_repo`` / needs_setup, red; keep ``clone`` in a local slot's
    actions -> red."""
    machine_roots_cache_clear()
    workspace_id = WorkspaceStore().create(name="Notes").id
    local = {"name": "notes", "repo": {"local": True}}
    call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": [local], "issued_at": ISSUED})
    unbound = _show(workspace_id)["notes"]["steps"][0]
    assert unbound["label"] == "Locate notes" and unbound["actions"] == ["locate"]
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "README.md").write_text("# notes\n", encoding="utf-8")
    row = call("runtime.workspace.slot.bind", {"workspace_id": workspace_id, "slot": "notes", "path": str(folder),
                                               "issued_at": ISSUED})["result"]["report"]
    assert row["checkout"] == "folder" and row["status"] == "ready"
    shown = _show(workspace_id)["notes"]
    assert shown["ready"] == "yes" and shown["blocking"] == [] and not (folder / ".git").exists()
