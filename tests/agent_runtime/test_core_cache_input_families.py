"""RT-CORE-CACHE-INPUT-FAMILIES: the turn- and worker-written families no
projection reads are outside the core cache's input closure.

Live 2026-10-20..25: 7 ``reason=fingerprint_mismatch`` misses whose ``diff=``
paths were ``chat_turn_reservations`` 16, ``work/ws_*`` git internals 9,
``chat_turn_settles`` 4, ``realm_sync_state`` 1. The first three are written on
every turn or fetch and read by no snapshot section; the fourth IS read (the
realm rows) and stays.

Two halves: the digest no longer moves for the three (each with a positive
control that a neighbouring INPUT still moves it), and a runtime reader audit —
a real ``build_snapshot`` over a store seeded with all three opens no file in
them, beside a control that the same spy sees the build's real reads.

Named sabotage: drop ``CHAT_TURN_RESERVATIONS_DIRNAME`` (or the settles name)
from ``_EXCLUDED_STORE_ENTRIES``, or ``WORK_DIRNAME`` from
``_EXCLUDED_NESTED_STORE_NAMES`` → the matching digest case reds.
"""

from __future__ import annotations

import builtins
import io
from pathlib import Path

import pytest

from agent_runtime import core_cache, paths
from agent_runtime.store import WorkspaceStore


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _families(ws_id: str) -> dict[str, Path]:
    return {
        "reservations": paths.chat_turn_reservations_dir() / "k.json",
        "settles": paths.chat_turn_settles_dir() / "s.json",
        "work_git": paths.default_brain_dir(ws_id) / ".git" / "FETCH_HEAD",
    }


@pytest.fixture
def seeded(isolate_agent_runtime_root):
    ws = WorkspaceStore().create(name="Families")
    family = _families(ws.id)
    for path in family.values():
        _write(path, "one")
    _write(paths.default_brain_dir(ws.id) / "TODO.md", "- row\n")
    return ws, family


@pytest.mark.parametrize("name", ["reservations", "settles", "work_git"])
def test_a_family_write_leaves_the_digest_unchanged(seeded, name):
    _ws, family = seeded
    before = core_cache.build_input_fingerprint()
    assert before is not None
    _write(family[name], "two, and longer")
    _write(family[name].with_name("added.json"), "{}")
    after = core_cache.build_input_fingerprint()
    assert after is not None
    assert after.digest == before.digest, name


@pytest.mark.parametrize(
    "neighbour",
    ["brain_note", "realm_sync_state"],
)
def test_a_neighbouring_input_still_moves_the_digest(seeded, neighbour):
    """Positive control: the exclusions are exactly as wide as audited."""

    ws, _family = seeded
    target = (
        paths.default_brain_dir(ws.id) / "TODO.md"
        if neighbour == "brain_note"
        else paths.store_root() / "realm_sync_state" / "realm_x.json"
    )
    before = core_cache.build_input_fingerprint()
    _write(target, "- moved, with more bytes\n")
    after = core_cache.build_input_fingerprint()
    assert after is not None and before is not None
    assert after.digest != before.digest, neighbour


def test_the_snapshot_build_reads_none_of_the_three_families(seeded, monkeypatch):
    _ws, family = seeded
    roots = [str(paths.chat_turn_reservations_dir()), str(paths.chat_turn_settles_dir()),
             str(family["work_git"].parent)]
    workspaces = str(paths.store_root() / "workspaces")
    opened: list[str] = []
    real_open = io.open

    def spy(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    from agent_runtime.snapshot import build_snapshot

    build_snapshot(build_info={"caller": "probe"})

    # Positive control: the spy sees a projection INPUT the build reads (the
    # workspace record), not merely the cache's own write-back.
    assert any(path.startswith(workspaces) for path in opened), opened[:20]
    read = [path for path in opened if any(path.startswith(root) for root in roots)]
    assert not read, read
