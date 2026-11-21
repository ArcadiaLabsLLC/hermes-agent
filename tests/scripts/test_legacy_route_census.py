"""The saved-route census counts a never-imported route with turns as pending, and writes nothing."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.store import ConversationStore
from tests.agent_runtime.legacy_conversation_seed import seed_route

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "legacy_route_census.py"
_spec = importlib.util.spec_from_file_location("legacy_route_census", _SCRIPT)
census_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(census_script)


def test_a_route_with_turns_and_no_migration_mark_is_pending_and_the_census_writes_nothing(tmp_path):
    root = tmp_path / "ns" / "agent-runtime"
    root.mkdir(parents=True)
    store = ConversationStore(root / census_script.ROUTES_FILE)
    scope = ConversationScope("actor", "a" * 64, "work")
    seed_route(store, scope, "lone", str(tmp_path), tmp_path, native_id="s1", turns=("t1",))
    migrated = seed_route(store, scope, "adopted", str(tmp_path), tmp_path, native_id="s2", turns=("t1",))
    store.reserve_migration(migrated, "persona", "personainst_1")
    seed_route(store, scope, "unused", str(tmp_path), tmp_path)
    (tmp_path / "other").mkdir()
    before = (root / census_script.ROUTES_FILE).read_bytes()

    total, held, unreadable = census_script.census([tmp_path])

    assert total == {"files": 1, "routes": 3, "with_turns": 2, "migrated": 1, "pending": 1}
    assert [found for _path, found in held] == [{"routes": 3, "with_turns": 2, "migrated": 1, "pending": 1}]
    assert unreadable == []
    assert (root / census_script.ROUTES_FILE).read_bytes() == before
