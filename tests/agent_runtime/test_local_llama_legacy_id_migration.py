"""The one-shot startup rewrite of ``local-llama-hermes`` -> ``llamacpp`` (h10b-fix, owner 2026-09-29)."""

from __future__ import annotations

import json
import logging
import sqlite3

from agent_runtime.local_llama_adapter import legacy_id_migration as migration

OLD, NEW = migration.RETIRED_PROVIDER_ID, "llamacpp"


def _json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, model_config TEXT)")
    conn.executemany("INSERT INTO sessions VALUES (?, ?)", [(sid, json.dumps(cfg)) for sid, cfg in rows])
    conn.commit()
    conn.close()


def _seed(home):
    store = home / "store"
    originals = {
        "agent": _json(store / "agents" / "p1.json", {"id": "p1", "provider": OLD, "model": "m"}),
        "cloud_agent": _json(store / "agents" / "p2.json", {"id": "p2", "provider": "anthropic"}),
        "instance": _json(store / "persona_instances" / "i1.json", {"id": "i1", "provider": OLD}),
        "archived": _json(store / "persona_instances_archive" / "x" / "i2.json", {"id": "i2", "provider": OLD}),
    }
    config = home / "config.yaml"
    config.write_text(
        "model:\n  provider: anthropic  # cloud default\n"
        "agent_runtime:\n  default_provider: 'local-llama-hermes'\n  personas:\n"
        "    p3:\n      provider: local-llama-hermes  # picked in the launcher\n"
        "notes: local-llama-hermes is mentioned here and stays\n",
        encoding="utf-8",
    )
    originals["config"] = config.read_text(encoding="utf-8")
    _db(home / "state.db", [
        ("s-old", {"mission_control_chat_model_override": {"provider": OLD, "model": "u"}}),
        ("s-cloud", {"mission_control_chat_model_override": {"provider": "openai", "model": "g"}}),
    ])
    return store, originals


def test_every_store_and_config_yaml_is_rewritten_backed_up_and_reported(tmp_path, caplog):
    home = tmp_path / "home"
    home.mkdir()
    store, originals = _seed(home)

    with caplog.at_level(logging.WARNING, logger=migration.__name__):
        report = migration.rewrite_retired_provider_id(home=home, store_root=store)

    assert json.loads((store / "agents" / "p1.json").read_text())["provider"] == NEW
    assert json.loads((store / "persona_instances" / "i1.json").read_text())["provider"] == NEW
    assert json.loads((store / "persona_instances_archive" / "x" / "i2.json").read_text())["provider"] == NEW
    assert (store / "agents" / "p2.json").read_text(encoding="utf-8") == originals["cloud_agent"]
    config = (home / "config.yaml").read_text(encoding="utf-8")
    assert "default_provider: 'llamacpp'" in config
    assert "      provider: llamacpp  # picked in the launcher\n" in config
    assert "provider: anthropic  # cloud default" in config
    assert "notes: local-llama-hermes is mentioned here and stays" in config
    conn = sqlite3.connect(str(home / "state.db"))
    stored = dict(conn.execute("SELECT id, model_config FROM sessions").fetchall())
    conn.close()
    assert json.loads(stored["s-old"])["mission_control_chat_model_override"]["provider"] == NEW
    assert json.loads(stored["s-cloud"])["mission_control_chat_model_override"]["provider"] == "openai"

    kinds = sorted((row["kind"], row["count"]) for row in report["rewritten"])
    assert kinds == [("config_yaml", 2), ("json_row", 1), ("json_row", 1), ("json_row", 1),
                     ("state_db_chat_override", 1)]
    assert report["errors"] == []
    for row in report["rewritten"]:  # every changed file was copied first, byte-identical
        assert row["backup"].startswith(report["backup_dir"])
    backups = {row["path"]: row["backup"] for row in report["rewritten"]}
    from pathlib import Path
    assert Path(backups[str(store / "agents" / "p1.json")]).read_text(encoding="utf-8") == originals["agent"]
    assert Path(backups[str(home / "config.yaml")]).read_text(encoding="utf-8") == originals["config"]
    backup_db = sqlite3.connect(backups[str(home / "state.db")])
    assert OLD in backup_db.execute("SELECT model_config FROM sessions WHERE id='s-old'").fetchone()[0]
    backup_db.close()
    assert sum("local_llama_legacy_id_rewritten" in r.getMessage() for r in caplog.records) == 5


def test_a_home_without_the_id_changes_nothing_and_backs_up_nothing(tmp_path):
    home = tmp_path / "home"
    store = home / "store"
    _json(store / "agents" / "p2.json", {"id": "p2", "provider": "anthropic"})
    (home / "config.yaml").write_text("model:\n  provider: anthropic\n", encoding="utf-8")
    report = migration.rewrite_retired_provider_id(home=home, store_root=store)
    assert report["rewritten"] == [] and report["backup_dir"] is None
    assert not (home / "backups").exists()


def test_it_runs_once_per_home(tmp_path, monkeypatch):
    from agent_runtime import paths
    import hermes_constants

    home = tmp_path / "home"
    home.mkdir()
    store, _ = _seed(home)
    monkeypatch.setattr(paths, "store_root", lambda: store)
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: home)

    first = migration.migrate_retired_provider_id_once()
    assert len(first["rewritten"]) == 5
    assert json.loads(migration.marker_path(store).read_text())["rewritten"] == first["rewritten"]
    _json(store / "agents" / "late.json", {"id": "late", "provider": OLD})
    assert migration.migrate_retired_provider_id_once() is None  # the marker: one-shot
    assert json.loads((store / "agents" / "late.json").read_text())["provider"] == OLD


def test_the_plugin_runs_it_at_load(monkeypatch):
    import importlib.util
    from pathlib import Path

    calls = []
    monkeypatch.setattr(migration, "migrate_retired_provider_id_once", lambda: calls.append(1))
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_llama_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _NullCtx:
        def __getattr__(self, name):
            return lambda *a, **k: None

    import hermes_cli.harness_parts.mission_chat_door_binding as door
    monkeypatch.setattr(door, "bind_mission_chat_door", lambda: None)
    module.register(_NullCtx())
    assert calls == [1]
