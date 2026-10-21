"""The store epoch guard (row RT-STORE-EPOCH; launcher plan EDITION_SWITCH_NAMESPACE_STORE §4). Temp roots only.

Owner ruling 2026-10-20: guard on a breaking-change epoch, never on the version. A build refuses a
store stamped above its own epoch, refuses to RAISE a store without the launcher's consent, and
otherwise opens without touching the epoch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import namespace_admin as admin
from agent_runtime import store_epoch as se
from hermes_cli import _namespace_bootstrap as ns

NS = "stagec-smoke"
BREAKING = ({"id": "x-reshape", "date": "2026-10-20", "store": "state.db", "breaking": True, "raises_to": 2,
             "reason": "test"},)
CONSENT = {"HERMES_LAUNCHER_SPAWNED": "1", "HERMES_STORE_EPOCH_CONSENT": "2"}


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    base = tmp_path / ".hermes"
    base.mkdir()
    return {"HERMES_DEPENDENCY_ROOT": str(base), "HERMES_NAMESPACES_DIR": str(tmp_path / "hermes-namespaces"),
            "HERMES_NAMESPACE": NS}


def _namespace(env: dict[str, str], epoch: object = "absent") -> Path:
    item = ns.layout(NS, env)
    item.root.mkdir(parents=True)
    record: dict[str, object] = {"schema": 1, "id": NS, "created_at": "2026-10-19T00:00:00+00:00"}
    if epoch != "absent":
        record["epoch"] = epoch
    item.manifest_path.write_text(json.dumps(record), encoding="utf-8")
    return item.manifest_path


@pytest.mark.parametrize(("stored", "mine", "registry", "extra", "verdict"), [
    (2, 1, (), {}, se.VERDICT_NEWER),                       # a newer store: refuse
    (None, 1, (), {}, se.VERDICT_NEWER),                    # unparseable: fail closed
    (1, 1, (), {}, se.VERDICT_OK),
    (0, 1, (), {}, se.VERDICT_OK),                          # older, and this build raises nothing above it
    (1, 2, BREAKING, {}, se.VERDICT_CONSENT_REQUIRED),      # would raise, no consent
    (1, 2, BREAKING, {"HERMES_STORE_EPOCH_CONSENT": "2"}, se.VERDICT_CONSENT_REQUIRED),  # consent outside the launcher
    (1, 2, BREAKING, {**CONSENT, "HERMES_STORE_EPOCH_CONSENT": "3"}, se.VERDICT_CONSENT_REQUIRED),  # another epoch's
    (1, 2, BREAKING, CONSENT, se.VERDICT_RAISE),
    (2, 2, BREAKING, {}, se.VERDICT_OK),
])
def test_the_verdict_table(stored, mine, registry, extra, verdict):
    assert se.decide(stored, extra, mine=mine, registry=registry).verdict == verdict


@pytest.mark.parametrize(("epoch", "stored"), [
    ("absent", 0), ({"value": 3}, 3), ({"value": "3"}, None), ({"value": True}, None), ({"value": -1}, None),
    ("3", None),
])
def test_a_missing_block_is_epoch_zero_and_a_bad_one_unparseable(epoch, stored):
    record = {} if epoch == "absent" else {"epoch": epoch}
    assert se.stored_epoch(record) == stored


def test_a_newer_store_is_refused_at_the_serve_entry_and_nothing_is_written(env):
    manifest = _namespace(env, {"value": se.STORE_EPOCH + 1})
    before = manifest.read_bytes()
    frames: list[dict] = []
    assert se.refuse_unreadable_store(frames.append, env) == se.EXIT_REFUSED
    assert [f["reason"] for f in frames] == [se.REFUSAL_NEWER]
    assert frames[0]["epoch"] == {"stored": se.STORE_EPOCH + 1, "mine": se.STORE_EPOCH, "verdict": "newer"}
    assert manifest.read_bytes() == before


def test_a_raise_needs_the_launchers_consent(env, monkeypatch):
    monkeypatch.setattr(se, "MIGRATION_REGISTRY", BREAKING)
    monkeypatch.setattr(se, "STORE_EPOCH", 2)
    manifest = _namespace(env, {"value": 1})
    before = manifest.read_bytes()
    frames: list[dict] = []
    assert se.refuse_unreadable_store(frames.append, env) == se.EXIT_REFUSED
    assert frames[0]["reason"] == se.REFUSAL_CONSENT_REQUIRED
    assert manifest.read_bytes() == before
    assert se.refuse_unreadable_store(frames.append, {**env, **CONSENT}) is None
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert record["epoch"]["value"] == 2 and record["last_written_by"]["edition"] in ("developer", "bundled")


def test_an_open_that_raises_nothing_never_moves_the_epoch(env):
    manifest = _namespace(env)  # no block: epoch 0, and this build's registry has no breaking entry
    assert se.refuse_unreadable_store(lambda _f: None, env) is None
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert "epoch" not in record and "at" in record["last_written_by"]


def test_the_serve_runs_the_guard_before_any_store_write(env, monkeypatch):
    """``ServeSession.run`` returns 2 on a newer store without reaching the root anchor."""
    from hermes_cli.harness_parts.serve.session import ServeSession

    _namespace(env, {"value": se.STORE_EPOCH + 1})
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    frames: list[dict] = []
    session = object.__new__(ServeSession)
    monkeypatch.setattr(ServeSession, "_boot_prelude",
                        lambda self: setattr(self, "frames", type("F", (), {"emit": staticmethod(frames.append)})()))

    def _wrote(self):
        raise AssertionError("the serve reached a store write past a refused epoch")

    monkeypatch.setattr(ServeSession, "_boot_anchor_and_skills", _wrote)
    assert session.run() == 2
    assert frames[-1]["event"] == "namespace_refused" and frames[-1]["reason"] == se.REFUSAL_NEWER


def test_probe_reports_the_epoch_and_refuses_only_a_newer_store(env, monkeypatch):
    _namespace(env, {"value": se.STORE_EPOCH + 1})
    out = ns.probe(env, NS)
    assert out["epoch"] == {"stored": se.STORE_EPOCH + 1, "mine": se.STORE_EPOCH, "verdict": "newer"}
    assert out["refusal"]["reason"] == "namespace_epoch_newer"
    ns.layout(NS, env).manifest_path.write_text(json.dumps({"schema": 1, "id": NS, "epoch": {"value": 1}}),
                                                encoding="utf-8")
    monkeypatch.setattr(se, "MIGRATION_REGISTRY", BREAKING)
    monkeypatch.setattr(se, "STORE_EPOCH", 2)
    out = ns.probe(env, NS)
    assert out["epoch"]["verdict"] == "consent_required" and out["refusal"] is None


def test_a_new_namespace_and_a_reset_are_stamped_with_this_builds_epoch(env):
    item = ns.layout(NS, env)
    assert ns.ensure_manifest(item)
    assert json.loads(item.manifest_path.read_text(encoding="utf-8"))["epoch"]["value"] == se.STORE_EPOCH
    item.manifest_path.write_text(json.dumps({"schema": 1, "id": NS, "epoch": {"value": 9}}), encoding="utf-8")
    admin.reset(NS, {k: v for k, v in env.items() if k != "HERMES_NAMESPACE"})
    assert json.loads(item.manifest_path.read_text(encoding="utf-8"))["epoch"]["value"] == se.STORE_EPOCH


def test_a_verb_refuses_a_newer_namespace(env):
    _namespace(env, {"value": se.STORE_EPOCH + 1})
    with pytest.raises(ns.NamespaceRefused) as caught:
        admin.epoch_admitted(admin.existing_namespace(NS, env), env)
    assert caught.value.reason is ns.Reason.EPOCH_NEWER


def test_the_release_lane_print(capsys):
    assert se.main() == 0
    assert json.loads(capsys.readouterr().out) == {"schema": 1, "store_epoch": se.STORE_EPOCH}
