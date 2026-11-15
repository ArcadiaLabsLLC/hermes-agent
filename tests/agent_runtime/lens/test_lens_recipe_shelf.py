"""Sharing a Lens monitor's recipe with its workspace, and adding one as a DRAFT (slice 1).

Row ``RT-LENS-RECIPE-SHELF-SHARE-AND-ADD``; plan
``docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md`` §2, §4, §5 and §7 rows 3–7.
Ruling ``OR-2026-11-09-lens-shared-recipes-opt-in``: only the recipe is shared, and this PC's
person chooses to turn it on.

One PC, no realm: a sealed monitor is shared, listed, withdrawn and added into its workspace on a
second home (the shelf file carried over by hand, as realm sync will carry it). Each guarantee
names the mutation that kills it; the reds are recorded in the commit that landed this file.

* only the operator's RPC and the persona tool call ``LensStore.create`` — killed by calling
  ``create`` from ``agent_runtime/realm_sync/pull.py`` (§7 row 3);
* the shelf cannot reach the Lens store — killed by ``from .store import LensStore`` in
  ``lens/recipe_shelf.py``;
* an added recipe cannot read a credential this PC already holds — killed by ``localize``
  returning the manifest unchanged (§7 row 4);
* an added ``act`` recipe may do nothing alone — killed by keeping ``automation.actions`` in
  ``localize`` (§7 row 5);
* a command or SQL source is never shared, at either door — killed by adding
  ``command_allowlisted`` to ``PORTABLE_FEED_KINDS`` (§7 row 6);
* no secret, Episode or receipt is in a shared recipe — killed by ``share`` writing the
  monitor's summary (``store.get``) instead of its sealed manifest (§7 row 7);
* the state table — killed by answering ``added`` whenever a monitor of the id exists.

No real network: the one read goes through an ``httpx.MockTransport``.
"""

from __future__ import annotations

import ast
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from agent_runtime import paths
from agent_runtime.events import EventLog
from agent_runtime.lens import recipe_shelf
from agent_runtime.lens.credentials import LensCredential, CredentialScheme
from agent_runtime.lens.episode import Episode, EpisodeState
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.recipe_shelf import (
    LENS_RECIPE_FAMILY,
    PORTABLE_FEED_KINDS,
    RECIPE_STATES,
    RecipeDocumentError,
    RecipeState,
    ShelfRecipe,
    localize,
    recipe_document,
    recipe_state,
)
from agent_runtime.lens.store import LensStore
from agent_runtime.lens.wire_value import WireError
from agent_runtime.realm_sync.document_family import DocumentStore, validate_document

RUNTIME = Path(__file__).resolve().parents[3] / "agent_runtime"
T0 = datetime(2026, 11, 15, 12, tzinfo=UTC)
SECRET = "zq7Wx-9cJq-Kp4Rv"
WORKSPACE = "ws_team"
URL = "https://status.example.invalid/health"


def _feed(feed_id: str = "api", **extra) -> dict:
    return {"version": 1, "id": feed_id, "kind": "http_json", "interval_ms": 5000,
            "source": {"url": URL, "selector": "$.cpu"}, **extra}


def _manifest(monitor_id: str = "site-health", *feeds: dict, **automation) -> dict:
    return {"version": 1, "monitor_id": monitor_id, "feeds": list(feeds) or [_feed(credential_ref="api")], "rules": [],
            "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0, **automation}, "persona_id": None}


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _ok(method: str, params: dict) -> dict:
    reply = _rpc(method, params)
    assert "result" in reply, reply
    return reply["result"]


def _reason(method: str, params: dict) -> tuple[str, str | None]:
    data = _rpc(method, params)["error"]["data"]
    return data["reason"], data.get("detail")


def _sealed(manifest: dict | None = None, workspace_id: str | None = WORKSPACE) -> str:
    manifest = manifest or _manifest()
    params = {"manifest": manifest} | ({} if workspace_id is None else {"workspace_id": workspace_id})
    _ok("runtime.lens.create", params)
    _ok("runtime.lens.seal", {"monitor_id": manifest["monitor_id"]})
    return manifest["monitor_id"]


def _shelf_file(recipe_id: str = "site-health", workspace_id: str = WORKSPACE) -> Path:
    return paths.lens_recipe_path(workspace_id, recipe_id)


def _second_pc(monkeypatch, tmp_path: Path) -> None:
    """Another home that holds only the shelf file — what a realm pull will leave there."""

    shelf = tmp_path / "carried.json"
    shutil.copyfile(_shelf_file(), shelf)
    home = tmp_path / "second-pc"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(home / "agent-runtime"))
    assert not LensStore().exists()
    _shelf_file().parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(shelf, _shelf_file())


# --- the journey: share, list, add as a draft, withdraw ------------------------------------


def test_a_sealed_monitor_is_shared_listed_added_as_a_draft_and_withdrawn(monkeypatch, tmp_path):
    shared = _ok("runtime.lens.recipe.share", {"monitor_id": _sealed()})
    assert (shared["recipe_id"], shared["workspace_id"], shared["state"]) == ("site-health", WORKSPACE, "added")
    assert shared["summary"] == {"level": "notify", "sources": [{"feed_id": "api", "kind": "http_json",
                                                                 "host": "status.example.invalid"}],
                                 "scheduled": False, "needs_credentials": ["api"], "private_network": False,
                                 "suggested_actions": []}

    _second_pc(monkeypatch, tmp_path)
    listed = _ok("runtime.lens.recipe.list", {"workspace_id": WORKSPACE})
    assert [(row["recipe_id"], row["state"]) for row in listed["recipes"]] == [("site-health", "not_added")]
    assert (listed["held"], listed["refused"]) == ([], []) and not LensStore().exists()  # a list writes nothing

    added = _ok("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "site-health"})
    assert (added["state"], added["sealed"], added["workspace_id"]) == ("draft", None, WORKSPACE)
    assert added["credentials"] == [{"feed_id": "api", "ref": "shared:site-health:api", "set": False,
                                     "rotated_at": None, "host": None}]
    # Nothing runs: a draft is not polled, and only seal + enable (this PC's person) change that.
    reads: list[str] = []
    poller = LensPoller(clock=lambda: T0, resolver=lambda host: ["93.184.216.34"], client=httpx.Client(
        transport=httpx.MockTransport(lambda r: reads.append(str(r.url)) or httpx.Response(200, json={"cpu": 1}))))
    assert poller.tick() == 0 and reads == []
    [row] = _ok("runtime.lens.recipe.list", {"workspace_id": WORKSPACE})["recipes"]
    assert row["state"] == "added"

    withdrawn = _ok("runtime.lens.recipe.withdraw", {"workspace_id": WORKSPACE, "recipe_id": "site-health"})
    assert (withdrawn["state"], withdrawn["manifest"], withdrawn["summary"]) == ("withdrawn", None, None)
    assert json.loads(_shelf_file().read_bytes()) == {"version": 1, "workspace_id": WORKSPACE, "withdrawn": True,
                                                      "monitor_id": "site-health", "manifest": None}
    assert _reason("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "site-health"}) \
        == ("recipe_withdrawn", "")
    assert LensStore().get("site-health")["state"] == "draft"  # a monitor already added is this PC's own
    events = [(evt.payload["recipe_id"], evt.payload["change"]) for _, evt in EventLog().iter_from_offset(0)
              if evt.type == "lens.recipe.changed"]
    assert events == [("site-health", "added"), ("site-health", "withdrawn")]


def test_an_update_plants_a_draft_and_never_rewrites_the_sealed_revision(monkeypatch, tmp_path):
    _ok("runtime.lens.recipe.share", {"monitor_id": _sealed()})
    first = _shelf_file().read_bytes()
    _second_pc(monkeypatch, tmp_path)
    _ok("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "site-health"})
    digest = _ok("runtime.lens.seal", {"monitor_id": "site-health"})["sealed"]["digest"]

    changed = json.loads(first)
    changed["manifest"]["feeds"][0]["interval_ms"] = 60000
    _shelf_file().write_bytes(json.dumps(changed).encode())  # the publisher's next version arrives
    [row] = _ok("runtime.lens.recipe.list", {"workspace_id": WORKSPACE})["recipes"]
    assert row["state"] == "update_available"
    assert LensStore().get("site-health")["sealed"]["digest"] == digest  # arriving changed nothing here

    updated = _ok("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "site-health"})
    assert updated["sealed"]["digest"] == digest and updated["draft"]["feeds"][0]["interval_ms"] == 60000
    assert updated["draft"]["feeds"][0]["credential_ref"] == "shared:site-health:api"  # the sign-in made for it stays


def test_the_verbs_refuse_by_name(monkeypatch):
    from agent_runtime.lens import store_scope

    monkeypatch.setattr(store_scope, "active_workspace_id", lambda: None)
    _ok("runtime.lens.create", {"manifest": _manifest("draft-only"), "workspace_id": WORKSPACE})
    assert _reason("runtime.lens.recipe.share", {"monitor_id": "draft-only"})[0] == "not_sealed"
    assert _reason("runtime.lens.recipe.share", {"monitor_id": "absent"})[0] == "monitor_not_found"
    assert _reason("runtime.lens.recipe.share", {"monitor_id": _sealed(_manifest("nowhere"), None)})[0] \
        == "recipe_needs_workspace"
    assert _reason("runtime.lens.recipe.list", {})[0] == "recipe_needs_workspace"
    assert _reason("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "absent"})[0] == "recipe_not_found"
    assert _rpc("runtime.lens.recipe.withdraw", {"workspace_id": WORKSPACE, "recipe_id": "absent"})["error"]["code"] \
        == _rpc("runtime.lens.get", {"monitor_id": "absent"})["error"]["code"]  # not found, not a conflict
    assert _reason("runtime.lens.recipe.add", {"recipe_id": "x", "monitor_id": "x"})[0] == "unknown_key"
    # The recipe's id is another workspace's monitor on this PC: never rewritten by an Add.
    _ok("runtime.lens.recipe.share", {"monitor_id": _sealed()})
    foreign = paths.lens_recipe_path("ws_other", "site-health")
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(recipe_document("ws_other", _manifest()))
    assert _reason("runtime.lens.recipe.add", {"workspace_id": "ws_other", "recipe_id": "site-health"})[0] \
        == "monitor_exists"
    [row] = _ok("runtime.lens.recipe.list", {"workspace_id": "ws_other"})["recipes"]
    assert row["state"] == "not_added"  # that monitor is not this workspace's
    # Two monitor ids one file name cannot tell apart: the second share does not overwrite the first.
    _ok("runtime.lens.recipe.share", {"monitor_id": _sealed(_manifest("a:b"))})
    assert _reason("runtime.lens.recipe.share", {"monitor_id": _sealed(_manifest("a_b"))})[0] == "recipe_id_taken"


def test_a_shelf_document_not_filed_where_it_says_is_refused_and_never_listed():
    misfiled = paths.lens_recipe_path(WORKSPACE, "elsewhere")
    misfiled.parent.mkdir(parents=True)
    misfiled.write_bytes(recipe_document(WORKSPACE, _manifest()))  # says site-health, filed as elsewhere
    paths.lens_recipe_path(WORKSPACE, "broken").write_bytes(b"{not json")
    listed = _ok("runtime.lens.recipe.list", {"workspace_id": WORKSPACE})
    assert listed["recipes"] == []
    assert listed["refused"] == [{"recipe_id": "broken", "reason": "unreadable_document"},
                                 {"recipe_id": "elsewhere", "reason": "recipe_misfiled"}]
    assert _reason("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "elsewhere"})[0] == "recipe_misfiled"


# --- §7 row 3 and the shelf's fence -------------------------------------------------------


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found |= {f"{'.' * node.level}{node.module or ''}.{alias.name}" for alias in node.names}
    return found


def test_only_the_operator_rpc_and_the_persona_tool_call_the_create_door():
    """A NEGATIVE over the source: a ``.create(...)`` call in any module that can name the Lens
    store. Over-approximates (any ``create`` in such a module counts), which is the safe direction."""

    callers = set()
    for path in RUNTIME.rglob("*.py"):
        name = path.relative_to(RUNTIME.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        reaches = name.startswith("agent_runtime/lens/") or any(
            "LensStore" in item or "serve_rpc.lens" in item or ".lens.store" in item or item.endswith("._store")
            for item in _imports(tree))
        if reaches and any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                           and node.func.attr == "create" for node in ast.walk(tree)):
            callers.add(name)
    assert callers == {"agent_runtime/serve_rpc/lens.py", "agent_runtime/serve_rpc/lens_recipes.py",
                       "agent_runtime/lens/tool.py"}, callers


def test_the_shelf_cannot_reach_the_lens_store():
    imported = _imports(ast.parse(Path(recipe_shelf.__file__).read_text(encoding="utf-8")))
    assert not [item for item in imported if "store" in item.split(".")[-2:] and "document_family" not in item
                and "store_events" not in item], imported
    assert not hasattr(recipe_shelf, "LensStore")


# --- §7 row 4: an added recipe starts signed out -------------------------------------------


def test_an_added_recipe_cannot_read_a_credential_this_pc_already_holds(monkeypatch):
    from agent_runtime.lens.sources import transport

    seen: list[str | None] = []
    real = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"cpu": 42})

    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(transport, "system_resolver", lambda host: ["93.184.216.34"])
    # This PC's own monitor, signed in as ``api`` for the very address the recipe reads.
    _ok("runtime.lens.create", {"manifest": _manifest("mine"), "workspace_id": "ws_mine"})
    assert _ok("runtime.lens.credential.set", {"ref": "api", "scheme": "bearer", "secret": SECRET})["set"] is True
    shelf = _shelf_file()
    shelf.parent.mkdir(parents=True)
    shelf.write_bytes(recipe_document(WORKSPACE, _manifest()))  # a peer's recipe naming ``api`` too

    draft = _ok("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "site-health"})["draft"]
    [read] = _ok("runtime.lens.preview", {"manifest": draft})["feeds"]
    assert (read["reason"], seen) == ("credential_missing", [])


def test_a_renamed_ref_past_the_id_bound_is_refused_never_cut():
    with pytest.raises(WireError) as refused:
        localize(_manifest("m", _feed(credential_ref="r" * 155)))  # 9 + 155 bytes: past the 160-byte id bound
    assert refused.value.code.value == "invalid_string"
    again = localize(localize(_manifest()))  # its own namespace is left alone: no stacking on a re-share
    assert again["feeds"][0]["credential_ref"] == "shared:site-health:api"


# --- §7 row 5: an added act recipe may do nothing alone ------------------------------------


def test_an_added_act_recipe_keeps_its_level_and_loses_its_actions():
    shared = _manifest("fixer", _feed(), level="act", actions=["write_file", "patch"]) | {"persona_id": "ops"}
    local = localize(shared)
    assert local["automation"] == {"level": "act", "when": "urgent", "daily_turn_cap": 0}
    assert shared["automation"]["actions"] == ["write_file", "patch"]  # the shelf's copy is not edited
    assert recipe_shelf.recipe_summary(shared)["suggested_actions"] == ["write_file", "patch"]


# --- §7 row 6: a command or SQL source is never shared, at either door ----------------------

_KIND_SOURCES = {
    "http_json": {"url": URL, "selector": "$.cpu"},
    "prometheus": {"base_url": "https://prom.example.invalid", "query": "up"},
    "push": {},
    "sql_readonly": {"database": "/srv/data/app.sqlite3", "query": "SELECT 1"},
    "command_allowlisted": {"argv": ["uptime"], "allow": [["uptime"]], "extract": "$.load"},
}


def _kind_manifest(kind: str) -> dict:
    from agent_runtime.lens.manifest import read_manifest

    return read_manifest(_manifest("m", {"version": 1, "id": "f", "kind": kind, "interval_ms": 5000,
                                         "source": _KIND_SOURCES[kind]}))


@pytest.mark.parametrize("kind", sorted(_KIND_SOURCES))
def test_only_portable_sources_are_shared_at_either_door(kind):
    from agent_runtime.lens.feed import AVAILABLE_FEED_KINDS

    assert {k.value for k in AVAILABLE_FEED_KINDS} == set(_KIND_SOURCES)  # the table is every kind there is
    portable = kind in {"http_json", "prometheus", "push"}
    assert (kind in PORTABLE_FEED_KINDS) is portable
    # The share door.
    _sealed(_kind_manifest(kind))
    reply = _rpc("runtime.lens.recipe.share", {"monitor_id": "m"})
    assert ("result" in reply) is portable
    if not portable:
        assert (reply["error"]["data"]["reason"], reply["error"]["data"]["detail"]) == ("recipe_not_portable", "f")
        assert not _shelf_file("m").exists()
    # The reading door every later arm shares (the family's own check): a planted document.
    raw = recipe_document(WORKSPACE, _kind_manifest(kind))
    if portable:
        validate_document(LENS_RECIPE_FAMILY, raw)
    else:
        with pytest.raises(RecipeDocumentError) as refused:
            validate_document(LENS_RECIPE_FAMILY, raw)
        assert refused.value.code == "recipe_not_portable"
        with pytest.raises(RecipeDocumentError):
            DocumentStore(LENS_RECIPE_FAMILY).write("ws_team/m", raw)
        _shelf_file("m").parent.mkdir(parents=True, exist_ok=True)
        _shelf_file("m").write_bytes(raw)
        listed = _ok("runtime.lens.recipe.list", {"workspace_id": WORKSPACE})
        assert (listed["recipes"], listed["refused"]) == ([], [{"recipe_id": "m", "reason": "recipe_not_portable"}])
        assert _reason("runtime.lens.recipe.add", {"workspace_id": WORKSPACE, "recipe_id": "m"})[0] == "recipe_not_portable"


# --- §7 row 7: nothing but the manifest is in a shared recipe ------------------------------


def test_no_secret_episode_or_receipt_is_in_a_shared_recipe():
    monitor_id = _sealed()
    _ok("runtime.lens.credential.set", {"ref": "api", "scheme": "bearer", "secret": SECRET})
    store = LensStore()
    episode = Episode(monitor_id=monitor_id, rule_id="cpu_hot", ordinal=1, first_seen=T0, last_seen=T0, count=1,
                      state=EpisodeState.ACTIVE)
    store.save_episode(episode)
    store.save_receipt({"episode_id": episode.id, "monitor_id": monitor_id, "turn_id": "turn-1", "session_id": None,
                        "started_ms": 1, "finished_ms": None, "outcome": "notified", "artifact_handles": [],
                        "files": [], "tool_admission": "none"})
    _ok("runtime.lens.recipe.share", {"monitor_id": monitor_id})

    published = _shelf_file().read_bytes()
    document = json.loads(published)
    assert set(document) == {"version", "workspace_id", "monitor_id", "withdrawn", "manifest"}
    assert document["manifest"] == store.get(monitor_id)["sealed"]["manifest"]
    credential = LensCredential(ref="api", scheme=CredentialScheme.BEARER, secret=SECRET)
    for needle in (*credential.secret_forms(), episode.id, "turn-1", "revision", "digest", "state", "recipe_hash"):
        assert needle.encode() not in published, needle


# --- the state table ------------------------------------------------------------------------


@pytest.mark.parametrize("withdrawn, monitor, state", [
    (False, None, RecipeState.NOT_ADDED),
    (False, {"recipe_hash": "h"}, RecipeState.ADDED),
    (False, {"recipe_hash": "older"}, RecipeState.UPDATE_AVAILABLE),
    (False, {"recipe_hash": None}, RecipeState.UPDATE_AVAILABLE),  # a monitor of the id that never met the shelf
    (True, None, RecipeState.WITHDRAWN),
    (True, {"recipe_hash": "h"}, RecipeState.WITHDRAWN),
    (True, {"recipe_hash": "older"}, RecipeState.WITHDRAWN),
])
def test_the_state_table(withdrawn, monitor, state):
    recipe = ShelfRecipe(recipe_id="m", workspace_id=WORKSPACE, monitor_id="m",
                         manifest=None if withdrawn else _manifest("m"), hash="h")
    assert recipe_state(recipe, monitor) is state
    assert len(RECIPE_STATES) == 6 and set(RECIPE_STATES.values()) == set(RecipeState)
