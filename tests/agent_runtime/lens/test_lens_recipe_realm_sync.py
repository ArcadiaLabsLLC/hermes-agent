"""A Lens watch shared on one PC reaches every teammate's PC as a recipe they can add (slice 2).

Row ``RT-LENS-RECIPE-REALM-SYNC-FAMILY``; plan
``docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md`` §3, §7 rows 1, 8, 9 and 10,
§8 and §9 slice 2. Ruling ``OR-2026-11-09-lens-shared-recipes-opt-in``: only the recipe is shared,
and this PC's person chooses to turn it on.

Two homes in one process (the sharer's PC and a teammate's), one realm, a local bare git origin:
the sharer shares a sealed monitor and publishes through ``publish_realm_sync``; the teammate's
``pull_realm_sync`` lands it on the shelf. Each guarantee names the mutation that kills it; the
reds are recorded in the commit that landed this file.

* a pulled recipe is listed ``not_added``, and nothing is created, sealed or polled — killed by
  calling ``LensStore().create`` inside ``apply_lens_recipe_pull`` (§7 row 1);
* a withdrawal reaches the peer, and the withdrawn recipe cannot be added — killed by deleting the
  shelf file in ``runtime.lens.recipe.withdraw`` instead of writing the withdrawn document (§7 row 9);
* an update never rewrites a running monitor — killed by the pull applier adding the recipe
  (``runtime.lens.recipe.add``) after it adopts one (§7 row 10);
* a realm cannot plant a recipe in another realm's workspace, or one filed under another
  monitor's name — killed by dropping ``admit`` from ``apply_lens_recipe_pull`` (§7 row 8);
* the publish carries only this realm's workspaces' recipes — killed by passing every token to
  ``document_publish_scan`` in ``lens_recipe_publish_scan``;
* a recipe both sides changed is HELD and named by ``runtime.lens.recipe.list`` — killed by
  ``_parked_recipes`` answering ``[]``;
* a share waits for the next publish (``unpublished_changes``) — killed by dropping
  ``lens_recipe_unpublished`` from the status flag;
* a realm re-key keeps an added recipe ``added`` — killed by not calling ``rekey_recipe_marks``
  in ``realm_rekey_outside._rekey_lens``.

No real network: the one read goes through an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from agent_runtime import paths
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.recipe_shelf import (
    LENS_RECIPE_FAMILY,
    apply_lens_recipe_pull,
    lens_recipe_publish_scan,
    recipe_document,
)
from agent_runtime.lens.store import LensStore

T0 = datetime(2026, 11, 16, 12, tzinfo=UTC)
URL = "https://status.example.invalid/health"


def _manifest(monitor_id: str = "site-health", interval_ms: int = 5000) -> dict:
    feed = {"version": 1, "id": "api", "kind": "http_json", "interval_ms": interval_ms,
            "source": {"url": URL, "selector": "$.cpu"}, "credential_ref": "api"}
    return {"version": 1, "monitor_id": monitor_id, "feeds": [feed], "rules": [],
            "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}, "persona_id": None}


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _ok(method: str, params: dict) -> dict:
    reply = _rpc(method, params)
    assert "result" in reply, reply
    return reply["result"]


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _clone(bare: Path, repo: Path) -> None:
    _git("clone", str(bare), str(repo))
    _git("-C", str(repo), "config", "user.email", "lens-recipe-sync-test@localhost")
    _git("-C", str(repo), "config", "user.name", "Lens Recipe Sync Test")


def _home(monkeypatch, tmp_path: Path, name: str) -> None:
    home = tmp_path / name
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(home / "agent-runtime"))


class Team:
    """The sharer's PC (``a``) and a teammate's (``b``), one realm and workspace, one origin."""

    def __init__(self, monkeypatch, tmp_path: Path):
        from agent_runtime.store import RealmStore, WorkspaceStore

        self.monkeypatch, self.tmp_path = monkeypatch, tmp_path
        self.bare = tmp_path / "origin.git"
        _git("init", "--bare", str(self.bare))
        seed = tmp_path / "seed"
        _clone(self.bare, seed)
        _git("-C", str(seed), "commit", "--allow-empty", "-m", "init")
        _git("-C", str(seed), "push", "origin", "HEAD")
        self.on("a")
        _clone(self.bare, tmp_path / "repo-a")
        realm = RealmStore().create(name="Lens Realm")
        realm.sync_manifest_ref = str(tmp_path / "repo-a")
        self.realm = RealmStore().save(realm)
        self.workspace = WorkspaceStore().create(name="Ops", realm_id=self.realm.id).id
        self.token = f"{paths.safe_path_token(self.workspace)}/site-health"

    def on(self, name: str) -> None:
        _home(self.monkeypatch, self.tmp_path, name)

    def join(self) -> None:
        """The teammate's PC: its own clone, the realm record and nothing else."""

        record = json.loads(paths.realm_path(self.realm.id).read_text(encoding="utf-8"))
        self.on("b")
        _clone(self.bare, self.tmp_path / "repo-b")
        record["sync_manifest_ref"] = str(self.tmp_path / "repo-b")
        paths.realm_path(self.realm.id).parent.mkdir(parents=True, exist_ok=True)
        paths.realm_path(self.realm.id).write_text(json.dumps(record), encoding="utf-8")

    def publish(self) -> dict:
        from agent_runtime.realm_sync import publish_realm_sync

        return publish_realm_sync(self.realm.id)

    def pull(self) -> dict:
        from agent_runtime.realm_sync import pull_realm_sync

        return pull_realm_sync(self.realm.id)["lens_recipe_sync"]

    def rows(self) -> list[tuple[str, str]]:
        listed = _ok("runtime.lens.recipe.list", {"workspace_id": self.workspace})
        return [(row["recipe_id"], row["state"]) for row in listed["recipes"]]

    def share(self, interval_ms: int = 5000) -> None:
        _ok("runtime.lens.create", {"manifest": _manifest(interval_ms=interval_ms), "workspace_id": self.workspace})
        _ok("runtime.lens.seal", {"monitor_id": "site-health"})
        _ok("runtime.lens.recipe.share", {"monitor_id": "site-health"})


@pytest.fixture
def team(isolate_agent_runtime_root, persisted_persona_samples, monkeypatch, tmp_path):
    return Team(monkeypatch, tmp_path)


def _poller(reads: list[str]) -> LensPoller:
    def handler(request: httpx.Request) -> httpx.Response:
        reads.append(str(request.url))
        return httpx.Response(200, json={"cpu": 1})

    return LensPoller(clock=lambda: T0, resolver=lambda host: ["93.184.216.34"],
                      client=httpx.Client(transport=httpx.MockTransport(handler)))


# --- §7 rows 1 and 9: published here, pulled there, never started; a withdrawal follows ---------


def test_a_recipe_shared_here_is_pulled_there_not_added_never_polled_and_its_withdrawal_follows(team):
    team.share()
    from agent_runtime.realm_sync import realm_sync_status

    assert realm_sync_status(team.realm.id)["unpublished_changes"] is True
    published = team.publish()
    assert published["lens_recipe_sync"]["published"] == [team.token]

    team.join()
    pulled = team.pull()
    assert (pulled["adopted"], pulled["refused"], pulled["source"]) == ([team.token], [], "subtree")
    assert team.rows() == [("site-health", "not_added")]
    # Nothing was created, sealed or enabled on the teammate's PC, and nothing is polled.
    assert not LensStore().exists() or LensStore().monitors() == []
    reads: list[str] = []
    assert _poller(reads).tick() == 0 and reads == []

    team.on("a")
    _ok("runtime.lens.recipe.withdraw", {"workspace_id": team.workspace, "recipe_id": "site-health"})
    team.publish()
    team.on("b")
    assert team.pull()["adopted"] == [team.token]
    assert team.rows() == [("site-health", "withdrawn")]
    reply = _rpc("runtime.lens.recipe.add", {"workspace_id": team.workspace, "recipe_id": "site-health"})
    assert reply["error"]["data"]["reason"] == "recipe_withdrawn"


# --- §7 row 10: an update reaches a running monitor as an offer, never as a rewrite ------------


def test_an_update_never_rewrites_a_running_monitor(team):
    team.share()
    team.publish()
    team.join()
    team.pull()
    _ok("runtime.lens.recipe.add", {"workspace_id": team.workspace, "recipe_id": "site-health"})
    _ok("runtime.lens.seal", {"monitor_id": "site-health"})
    _ok("runtime.lens.enable", {"monitor_id": "site-health"})
    digest = LensStore().get("site-health")["sealed"]["digest"]
    assert team.rows() == [("site-health", "added")]

    team.on("a")
    team.share(interval_ms=60000)  # the sharer's next version: a draft over the sealed one, sealed, re-shared
    team.publish()
    team.on("b")
    assert team.pull()["adopted"] == [team.token]
    monitor = LensStore().get("site-health")
    assert (monitor["sealed"]["digest"], monitor["state"], monitor["draft"]) == (digest, "enabled", None)
    assert team.rows() == [("site-health", "update_available")]

    updated = _ok("runtime.lens.recipe.add", {"workspace_id": team.workspace, "recipe_id": "site-health"})
    assert updated["sealed"]["digest"] == digest and updated["draft"]["feeds"][0]["interval_ms"] == 60000


# --- a recipe both sides changed is HELD, and the list names it ---------------------------------


def test_a_recipe_both_sides_changed_is_held_and_listed_as_held(team):
    team.share()
    team.publish()
    team.join()
    team.pull()
    _ok("runtime.lens.recipe.add", {"workspace_id": team.workspace, "recipe_id": "site-health"})
    _ok("runtime.lens.seal", {"monitor_id": "site-health"})
    _ok("runtime.lens.recipe.share", {"monitor_id": "site-health"})  # the teammate re-shares its own copy

    team.on("a")
    team.share(interval_ms=60000)
    team.publish()
    team.on("b")
    assert team.pull()["held"] == [team.token]
    assert _ok("runtime.lens.recipe.list", {"workspace_id": team.workspace})["held"] == ["site-health"]


# --- §7 row 8 and the publish scope: one realm's recipes only, filed where they say ----------------


def _plant(subtree: Path, token: str, raw: bytes) -> None:
    target = subtree / "store" / paths.LENS_RECIPES_DIRNAME / f"{token}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def test_a_realm_cannot_plant_a_recipe_in_another_realms_workspace_or_under_another_name(
        isolate_agent_runtime_root, tmp_path):
    subtree = tmp_path / "subtree"
    _plant(subtree, "ws_foreign/site-health", recipe_document("ws_foreign", _manifest()))
    _plant(subtree, "ws_ours/other", recipe_document("ws_ours", _manifest()))  # site-health, filed as "other"
    _plant(subtree, "ws_ours/site-health", recipe_document("ws_ours", _manifest()))

    summary = apply_lens_recipe_pull("realm_x", subtree, ["ws_ours"]).as_dict()
    assert summary["adopted"] == ["ws_ours/site-health"]
    assert sorted((row["key"], row["code"]) for row in summary["refused"]) == [
        ("ws_foreign/site-health", "recipe_outside_realm"), ("ws_ours/other", "recipe_misfiled")]
    assert not paths.lens_recipe_path("ws_foreign", "site-health").exists()
    assert not paths.lens_recipe_path("ws_ours", "other").exists()
    assert summary["upstream_absent"] == []


def test_the_publish_carries_only_this_realms_workspaces_recipes(isolate_agent_runtime_root):
    from agent_runtime.realm_sync.document_family import DocumentStore

    store = DocumentStore(LENS_RECIPE_FAMILY)
    store.write("ws_ours/site-health", recipe_document("ws_ours", _manifest()))
    store.write("ws_other/site-health", recipe_document("ws_other", _manifest()))
    scan = lens_recipe_publish_scan(["ws_ours"])
    assert sorted(scan.hashes) == ["ws_ours/site-health"] and scan.refused == []
    assert [artifact.relative_path for artifact in scan.artifacts] == ["store/lens_recipes/ws_ours/site-health.json"]
    assert {artifact.kind for artifact in scan.artifacts} == {"lens_recipe"}


# --- a realm re-key keeps an added recipe on its version ----------------------------------------


def test_a_realm_rekey_keeps_an_added_recipe_added(isolate_agent_runtime_root):
    from agent_runtime.realm_rekey import RekeyMap, _step_content, _step_rename
    from agent_runtime.realm_rekey_outside import _rekey_lens

    shelf = paths.lens_recipe_path("ws_old", "site-health")
    shelf.parent.mkdir(parents=True)
    shelf.write_bytes(recipe_document("ws_old", _manifest()))
    _ok("runtime.lens.recipe.add", {"workspace_id": "ws_old", "recipe_id": "site-health"})
    _ok("runtime.lens.seal", {"monitor_id": "site-health"})
    assert _ok("runtime.lens.recipe.list", {"workspace_id": "ws_old"})["recipes"][0]["state"] == "added"

    mapping = RekeyMap(realm_old="realm_old", realm_new="realm_new", workspaces={"ws_old": "ws_new"})
    root = paths.store_root()
    _step_content(root, mapping)
    _step_rename(root, mapping)
    _rekey_lens(mapping)
    [row] = _ok("runtime.lens.recipe.list", {"workspace_id": "ws_new"})["recipes"]
    assert (row["workspace_id"], row["state"]) == ("ws_new", "added")
